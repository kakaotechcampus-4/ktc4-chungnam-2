"""
게스트 → 카카오 전환 기록 합치기 끝단(#560) — 6개 모듈(maps·pins·recommend·shortlist·notifications·feedback)의
실제 `reassign_user`를 대역 없이 쓴다. 카카오 HTTP 응답만 기존 auth 테스트의 대역을 쓴다.

흐름: 방장이 만든 지도에 게스트가 POST /auth/guest로 들어가 핀·반응·확정·추천 기록·알림·피드백을 만든 뒤,
게스트 세션으로 GET /auth/kakao/login → 콜백. 카카오 계정이 이미 그 지도의 구성원인 경우와 아닌 경우를 모두 본다.
"""

import time
import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from auth import router as auth_router
from auth.models import User
from auth.testing import session_cookie
from auth.tests.test_router import _mock_kakao_login, kakao_configured  # noqa: F401 — kakao_configured는 픽스처
from feedback.models import Feedback
from maps.models import Membership
from notifications.models import Notification
from pins.models import Pin, Reaction
from recommend.models import RecommendRun
from shortlist.models import ShortlistItem

REGION = {"label": "부산", "lat": 35.1796, "lng": 129.0756}
NEW_KAKAO_ID = 9001   # 이 지도에 아직 없는 카카오 계정
B_KAKAO_ID = "pb"     # two_users의 user_b(영희) — conftest의 provider_user_id


@pytest.fixture(autouse=True)
def _fresh_limiter():
    auth_router.guest_join_limiter._hits.clear()
    yield
    auth_router.guest_join_limiter._hits.clear()


def _pin(client, map_id, body):
    r = client.post(f"/maps/{map_id}/pins", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


class World:
    """게스트가 기록을 쌓아 둔 지도. b_exists면 카카오 계정 B(user_b)가 이미 구성원이고 같은 핀에 반응해 둔 상태."""

    def __init__(self, app_client, db_session, pin_body, *, b_exists):
        app = app_client.app
        self.db = db_session
        self.owner = TestClient(app, cookies=session_cookie("user_a"))
        self.b = TestClient(app, cookies=session_cookie("user_b"))
        self.guest = TestClient(app)
        self.b_exists = b_exists

        self.map_id = self.owner.post("/maps", json={"title": "부산", "start_date": "2026-11-01",
                                                     "end_date": "2026-11-03", "region": REGION}).json()["id"]
        token = self.owner.post(f"/maps/{self.map_id}/invite").json()["token"]
        if b_exists:
            assert self.b.post(f"/invites/{token}/accept").status_code == 200
        self.owner_pin = _pin(self.owner, self.map_id, pin_body("seongsu-kalguksu"))
        if b_exists:
            assert self.b.put(f"/pins/{self.owner_pin}/reaction", json={"type": "like"}).status_code == 200

        joined = self.guest.post("/auth/guest", json={"display_name": "손님", "invite_token": token})
        assert joined.status_code == 201, joined.text
        self.guest_id = joined.json()["user"]["id"]
        self.guest_cookie = self.guest.cookies.get("session")

        # 게스트의 기록: 핀 1, 반응 1(방장 핀에 ♥ — B가 있으면 B의 반응과 겹친다), 확정 1, 추천 run 1, 피드백 1
        self.guest_pin = _pin(self.guest, self.map_id, pin_body("hongdae-ramen"))
        assert self.guest.put(f"/pins/{self.owner_pin}/reaction", json={"type": "like"}).status_code == 200
        assert self.guest.post(f"/maps/{self.map_id}/shortlist", json={"pin_id": self.guest_pin}).status_code == 201
        self.run = RecommendRun(id=uuid.uuid4(), map_id=self.map_id, category="음식점",
                                requested_by=self.guest_id, status="done")
        db_session.add(self.run)
        db_session.flush()
        assert self.guest.post("/feedback", json={"message": "좋아요", "map_id": self.map_id}).status_code == 201
        # 방장이 게스트 핀에 반응 → 게스트가 pin_reaction 알림을 받는다
        assert self.owner.put(f"/pins/{self.guest_pin}/reaction", json={"type": "like"}).status_code == 200

    def close(self):
        for c in (self.owner, self.b, self.guest):
            c.close()

    def convert(self, monkeypatch):
        """게스트 세션으로 카카오 로그인 시작 → 콜백. 콜백 응답을 돌려준다."""
        _mock_kakao_login(monkeypatch, kakao_id=B_KAKAO_ID if self.b_exists else NEW_KAKAO_ID, nickname="영희")
        start = self.guest.get("/auth/kakao/login", follow_redirects=False)
        assert start.status_code == 302, start.text
        state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
        resp = self.guest.get("/auth/kakao/callback", params={"code": "auth-code", "state": state}, follow_redirects=False)
        self.db.expire_all()
        return resp

    def kakao_user_id(self):
        if self.b_exists:
            return "user_b"
        return self.db.query(User).filter_by(provider="kakao", provider_user_id=str(NEW_KAKAO_ID)).one().id


@pytest.fixture(params=[True, False], ids=["B가 이미 구성원", "B가 새 계정"])
def world(request, app_client, two_users, db_session, pin_body):
    w = World(app_client, db_session, pin_body, b_exists=request.param)
    yield w
    w.close()


def _query(resp) -> dict:
    return parse_qs(urlparse(resp.headers["location"]).query)


def test_conversion_moves_every_record_to_the_kakao_account(world, db_session, kakao_configured, monkeypatch):
    resp = world.convert(monkeypatch)
    kakao = world.kakao_user_id()

    assert resp.status_code == 302
    assert _query(resp).get("guest_merged") == ["true"] and "login_error" not in _query(resp)
    assert any(h.startswith("session=") for h in resp.headers.get_list("set-cookie"))

    # 핀 작성자·확정 항목·추천 run·피드백·알림이 카카오 계정으로 옮겨졌다
    assert db_session.get(Pin, uuid.UUID(world.guest_pin)).created_by == kakao
    assert [i.added_by for i in db_session.query(ShortlistItem).filter_by(map_id=world.map_id)] == [kakao]
    assert db_session.get(RecommendRun, world.run.id).requested_by == kakao
    assert db_session.query(Feedback).filter_by(map_id=world.map_id).one().user_id == kakao
    reaction_alerts = db_session.query(Notification).filter_by(type="pin_reaction", pin_id=world.guest_pin).all()
    assert [n.user_id for n in reaction_alerts] == [kakao]
    assert db_session.query(Notification).filter_by(user_id=world.guest_id).count() == 0

    # 반응: 게스트 것은 카카오 계정으로 옮겨지되, 같은 핀에 B의 반응이 이미 있으면 B의 것이 유지된다
    on_owner_pin = db_session.query(Reaction).filter_by(pin_id=uuid.UUID(world.owner_pin)).all()
    assert [r.user_id for r in on_owner_pin if r.user_id != "user_a"] == [kakao]   # 방장 본인의 반응은 따로 둔다
    assert db_session.query(Reaction).filter_by(user_id=world.guest_id).count() == 0
    if world.b_exists:
        assert [(r.user_id, r.type) for r in on_owner_pin if r.user_id != "user_a"] == [("user_b", "like")]

    # 게스트 행은 지워지고 이전 게스트 쿠키는 더는 통하지 않는다
    assert db_session.get(User, world.guest_id).deleted_at is not None
    stale = TestClient(world.guest.app, cookies={"session": world.guest_cookie})
    assert stale.get("/auth/me").status_code == 401
    stale.close()

    # 멤버십은 카카오 계정 하나뿐이고 구성원 수가 일관된다(방장 + 카카오 계정)
    rows = db_session.query(Membership).filter_by(map_id=world.map_id).all()
    assert sorted(m.user_id for m in rows if m.user_id != world.guest_id) == sorted(["user_a", kakao])
    assert [m.user_id for m in rows].count(kakao) == 1 and all(m.user_id != world.guest_id for m in rows)
    assert world.owner.get(f"/maps/{world.map_id}").json()["member_count"] == 2

    # 응답이 준 세션은 카카오 계정이다
    me = world.guest.get("/auth/me")
    assert me.status_code == 200 and me.json()["id"] == kakao and me.json()["is_guest"] is False


def test_a_failing_module_leaves_the_guest_untouched_but_login_succeeds(world, db_session, kakao_configured, monkeypatch):
    import feedback.api as feedback_api

    def boom(db, **kwargs):
        raise RuntimeError("feedback step failed")

    monkeypatch.setattr(feedback_api, "reassign_user", boom)   # 마지막 단계 — 앞 단계(maps·pins…)의 쓰기도 되돌아가야 한다

    resp = world.convert(monkeypatch)

    assert _query(resp).get("guest_merged") == ["false"] and "login_error" not in _query(resp)
    assert any(h.startswith("session=") for h in resp.headers.get_list("set-cookie"))   # 카카오 로그인은 성공
    guest = db_session.get(User, world.guest_id)
    assert guest.deleted_at is None
    assert db_session.get(Pin, uuid.UUID(world.guest_pin)).created_by == world.guest_id
    assert [i.added_by for i in db_session.query(ShortlistItem).filter_by(map_id=world.map_id)] == [world.guest_id]
    assert db_session.get(RecommendRun, world.run.id).requested_by == world.guest_id
    assert db_session.query(Feedback).filter_by(map_id=world.map_id).one().user_id == world.guest_id
    assert db_session.query(Membership).filter_by(map_id=world.map_id, user_id=world.guest_id).count() == 1
    assert db_session.query(Reaction).filter_by(user_id=world.guest_id).count() == 1
    assert db_session.query(Notification).filter(Notification.user_id == world.guest_id,
                                                 Notification.type == "pin_reaction", Notification.pin_id == world.guest_pin).count() == 1

    kakao = world.kakao_user_id()
    me = world.guest.get("/auth/me")   # 응답 쿠키는 카카오 세션 — 로그인은 됐다
    assert me.status_code == 200 and me.json()["id"] == kakao
