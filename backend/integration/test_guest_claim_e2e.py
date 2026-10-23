"""
게스트 → 카카오 전환 끝단(#560, #694) — 7개 모듈(maps·pins·recommend·shortlist·notifications·feedback·agent)의
실제 `reassign_user`를 대역 없이 쓴다. 카카오 HTTP 응답만 기존 auth 테스트의 대역을 쓴다.

흐름: 방장이 만든 지도에 게스트가 POST /auth/guest로 들어가 핀·반응·확정·추천 기록·알림·피드백·agent 열람과 코스 요청을
만든 뒤, 게스트 세션으로 GET /auth/kakao/login → 콜백. 두 갈래를 본다.
- 처음 쓰는 카카오 계정: 게스트 계정에 카카오 로그인을 붙인다. 사용자 id·이름·기록이 그대로다
- 이미 쓰던 카카오 계정(B): 게스트 기록을 B로 옮기고 게스트를 지운다. B가 그 지도의 구성원인 경우와 아닌 경우
"""

import uuid
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from agent.course.models import AgentCourseRun
from agent.models import AgentSuggestionView
from agent.tests import rows as agent_rows
from auth import router as auth_router
from auth.models import User, UserIdentity
from auth.testing import session_cookie
from auth.tests.test_router import _mock_kakao_login, kakao_configured  # noqa: F401 — kakao_configured는 픽스처
from feedback.models import Feedback
from maps.models import Membership
from notifications.models import Notification
from pins.models import Pin, Reaction
from recommend.models import RecommendRun
from shortlist.models import ShortlistItem

REGION = {"label": "부산", "lat": 35.1796, "lng": 129.0756}
NEW_KAKAO_ID = 9001   # 아무 사용자에게도 없는 카카오 계정
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


def _query(resp) -> dict:
    return parse_qs(urlparse(resp.headers["location"]).query)


def _convert(client, db_session, monkeypatch, kakao_id):
    """이 client의 세션으로 카카오 로그인 시작 → 콜백. 콜백 응답을 돌려준다."""
    _mock_kakao_login(monkeypatch, kakao_id=kakao_id, nickname="카카오 닉네임")
    start = client.get("/auth/kakao/login", follow_redirects=False)
    assert start.status_code == 302, start.text
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    resp = client.get("/auth/kakao/callback", params={"code": "auth-code", "state": state}, follow_redirects=False)
    db_session.expire_all()
    return resp


class World:
    """게스트가 기록을 쌓아 둔 지도. b_member면 카카오 계정 B(user_b)가 이미 구성원이고 같은 핀에 반응해 둔 상태."""

    def __init__(self, app_client, db_session, pin_body, *, b_member):
        app = app_client.app
        self.db = db_session
        self.owner = TestClient(app, cookies=session_cookie("user_a"))
        self.b = TestClient(app, cookies=session_cookie("user_b"))
        self.guest = TestClient(app)

        self.map_id = self.owner.post("/maps", json={"title": "부산", "start_date": "2026-11-01",
                                                     "end_date": "2026-11-03", "region": REGION}).json()["id"]
        self.token = self.owner.post(f"/maps/{self.map_id}/invite").json()["token"]
        if b_member:
            assert self.b.post(f"/invites/{self.token}/accept").status_code == 200
        self.owner_pin = _pin(self.owner, self.map_id, pin_body("seongsu-kalguksu"))
        if b_member:
            assert self.b.put(f"/pins/{self.owner_pin}/reaction", json={"type": "like"}).status_code == 200

        joined = self.guest.post("/auth/guest", json={"display_name": "손님", "invite_token": self.token})
        assert joined.status_code == 201, joined.text
        self.guest_id = joined.json()["user"]["id"]
        self.guest_cookie = self.guest.cookies.get("session")

        # 게스트의 기록: 핀 1, 반응 1(방장 핀에 ♥ — B가 있으면 B의 반응과 겹친다), 확정 1, 추천 run 1, 피드백 1,
        # agent 제안 열람 1, 끝난 코스 요청 1
        self.guest_pin = _pin(self.guest, self.map_id, pin_body("hongdae-ramen"))
        assert self.guest.put(f"/pins/{self.owner_pin}/reaction", json={"type": "like"}).status_code == 200
        assert self.guest.post(f"/maps/{self.map_id}/shortlist", json={"pin_id": self.guest_pin}).status_code == 201
        self.run = RecommendRun(id=uuid.uuid4(), map_id=self.map_id, category="음식점",
                                requested_by=self.guest_id, status="done")
        db_session.add(self.run)
        self.suggestion = agent_rows.suggestion(db_session, self.map_id)
        agent_rows.view(db_session, self.suggestion.id, self.guest_id)
        self.course = AgentCourseRun(id=uuid.uuid4(), map_id=self.map_id, requested_by=self.guest_id, status="done",
                                     input={"request_text": "", "member_constraints": []},
                                     snapshot_at=agent_rows.NOW, snapshot_pin_ids=[])
        db_session.add(self.course)
        db_session.flush()
        assert self.guest.post("/feedback", json={"message": "좋아요", "map_id": self.map_id}).status_code == 201
        # 방장이 게스트 핀에 반응 → 게스트가 pin_reaction 알림을 받는다
        assert self.owner.put(f"/pins/{self.guest_pin}/reaction", json={"type": "like"}).status_code == 200

    def close(self):
        for c in (self.owner, self.b, self.guest):
            c.close()

    def convert(self, monkeypatch, kakao_id):
        return _convert(self.guest, self.db, monkeypatch, kakao_id)

    def owners(self):
        """게스트가 만든 기록 각각의 지금 주인."""
        db = self.db
        return {
            "pin": db.get(Pin, uuid.UUID(self.guest_pin)).created_by,
            "shortlist": [i.added_by for i in db.query(ShortlistItem).filter_by(map_id=self.map_id)],
            "recommend": db.get(RecommendRun, self.run.id).requested_by,
            "feedback": db.query(Feedback).filter_by(map_id=self.map_id).one().user_id,
            "notification": [n.user_id for n in db.query(Notification).filter_by(type="pin_reaction", pin_id=self.guest_pin)],
            "suggestion_view": [v.user_id for v in db.query(AgentSuggestionView).filter_by(suggestion_id=self.suggestion.id)],
            "course_run": db.get(AgentCourseRun, self.course.id).requested_by,
        }


def _all_owned_by(user_id) -> dict:
    return {
        "pin": user_id, "shortlist": [user_id], "recommend": user_id, "feedback": user_id,
        "notification": [user_id], "suggestion_view": [user_id], "course_run": user_id,
    }


# ---- 처음 쓰는 카카오 계정: 게스트 계정에 카카오 로그인을 붙인다 ----

@pytest.fixture()
def new_world(app_client, two_users, db_session, pin_body):
    w = World(app_client, db_session, pin_body, b_member=False)
    yield w
    w.close()


def test_first_kakao_login_keeps_the_same_user_and_every_record(new_world, db_session, kakao_configured, monkeypatch):
    w = new_world
    resp = w.convert(monkeypatch, NEW_KAKAO_ID)

    assert resp.status_code == 302
    assert _query(resp).get("guest_merged") == ["true"] and "login_error" not in _query(resp)
    assert any(h.startswith("session=") for h in resp.headers.get_list("set-cookie"))

    # 사용자 id·이름 그대로, 초대 토큰은 비웠고 카카오 수단이 붙었다
    guest = db_session.get(User, w.guest_id)
    assert (guest.display_name, guest.guest_invite_token, guest.deleted_at) == ("손님", None, None)
    assert db_session.query(UserIdentity).filter_by(user_id=w.guest_id).one().provider_user_id == str(NEW_KAKAO_ID)
    assert db_session.query(User).count() == 3   # 방장, B, 게스트였던 사람 — 새 사용자는 없다

    # 다른 모듈의 기록은 그대로다
    assert w.owners() == _all_owned_by(w.guest_id)
    assert db_session.query(Reaction).filter_by(user_id=w.guest_id).count() == 1
    assert db_session.query(Membership).filter_by(map_id=w.map_id, user_id=w.guest_id).count() == 1
    assert w.owner.get(f"/maps/{w.map_id}").json()["member_count"] == 2

    # 같은 사용자라 게스트 때 받은 쿠키도 통하고, 이제 게스트가 아니다
    assert w.guest.get("/auth/me").json() == {"id": w.guest_id, "display_name": "손님", "is_guest": False}
    stale = TestClient(w.guest.app, cookies={"session": w.guest_cookie})
    assert stale.get("/auth/me").json()["id"] == w.guest_id
    stale.close()
    created = w.guest.post("/maps", json={"title": "내 지도", "start_date": "2026-12-01", "end_date": "2026-12-02"})
    assert created.status_code == 201, created.text   # 게스트 제한(지도 만들기 불가)이 풀렸다

    # 로그아웃 뒤 같은 카카오로 다시 로그인하면 같은 사람이다(붙이기·합치기 없는 보통 로그인)
    w.guest.cookies.clear()
    again = w.convert(monkeypatch, NEW_KAKAO_ID)
    assert "guest_merged" not in _query(again)
    assert w.guest.get("/auth/me").json()["id"] == w.guest_id


def test_a_later_guest_with_that_kakao_account_merges_into_the_converted_user(
    new_world, db_session, kakao_configured, monkeypatch,
):
    """처음 전환으로 카카오가 붙은 사람은 이제 "이미 쓰던 카카오 계정"이다 — 다른 게스트가 같은 카카오로 오면 합친다."""
    w = new_world
    w.convert(monkeypatch, NEW_KAKAO_ID)
    other = TestClient(w.guest.app)
    joined = other.post("/auth/guest", json={"display_name": "두 번째 손님", "invite_token": w.token})
    assert joined.status_code == 201, joined.text
    second_id = joined.json()["user"]["id"]

    resp = _convert(other, db_session, monkeypatch, NEW_KAKAO_ID)

    assert _query(resp).get("guest_merged") == ["true"]
    assert db_session.get(User, second_id).deleted_at is not None
    assert other.get("/auth/me").json()["id"] == w.guest_id
    assert db_session.query(Membership).filter_by(map_id=w.map_id, user_id=w.guest_id).count() == 1
    assert w.owner.get(f"/maps/{w.map_id}").json()["member_count"] == 2
    other.close()


# ---- 이미 쓰던 카카오 계정(B): 기록을 옮긴다 ----

@pytest.fixture(params=[True, False], ids=["B가 이미 구성원", "B가 구성원이 아님"])
def b_world(request, app_client, two_users, db_session, pin_body):
    w = World(app_client, db_session, pin_body, b_member=request.param)
    yield w
    w.close()


def test_existing_kakao_account_receives_every_record(b_world, db_session, kakao_configured, monkeypatch):
    w = b_world
    resp = w.convert(monkeypatch, B_KAKAO_ID)

    assert resp.status_code == 302
    assert _query(resp).get("guest_merged") == ["true"] and "login_error" not in _query(resp)
    assert any(h.startswith("session=") for h in resp.headers.get_list("set-cookie"))

    # 핀 작성자·확정 항목·추천 run·피드백·알림·agent 열람과 코스 요청이 B로 옮겨졌다
    assert w.owners() == _all_owned_by("user_b")
    assert db_session.query(Notification).filter_by(user_id=w.guest_id).count() == 0

    # 반응: 게스트 것은 B로 옮겨지되, 같은 핀에 B의 반응이 이미 있으면 B의 것이 유지된다
    on_owner_pin = db_session.query(Reaction).filter_by(pin_id=uuid.UUID(w.owner_pin)).all()
    assert [r.user_id for r in on_owner_pin if r.user_id != "user_a"] == ["user_b"]   # 방장 본인의 반응은 따로 둔다
    assert db_session.query(Reaction).filter_by(user_id=w.guest_id).count() == 0

    # 게스트 행은 지워지고 이전 게스트 쿠키는 더는 통하지 않는다. 게스트에는 수단을 붙이지 않았다
    assert db_session.get(User, w.guest_id).deleted_at is not None
    assert db_session.query(UserIdentity).filter_by(user_id=w.guest_id).count() == 0
    stale = TestClient(w.guest.app, cookies={"session": w.guest_cookie})
    assert stale.get("/auth/me").status_code == 401
    stale.close()

    # 멤버십은 B 하나뿐이고 구성원 수가 일관된다(방장 + B)
    rows = db_session.query(Membership).filter_by(map_id=w.map_id).all()
    assert sorted(m.user_id for m in rows if m.user_id != w.guest_id) == ["user_a", "user_b"]
    assert all(m.user_id != w.guest_id for m in rows)
    assert w.owner.get(f"/maps/{w.map_id}").json()["member_count"] == 2

    # 응답이 준 세션은 B이고 이름도 B의 것이다
    assert w.guest.get("/auth/me").json() == {"id": "user_b", "display_name": "영희", "is_guest": False}


def test_a_failing_module_leaves_the_guest_untouched_but_login_succeeds(b_world, db_session, kakao_configured, monkeypatch):
    import agent.api as agent_api

    def boom(db, **kwargs):
        raise RuntimeError("agent step failed")

    monkeypatch.setattr(agent_api, "reassign_user", boom)   # 마지막 단계 — 앞 단계(maps·pins…)의 쓰기도 되돌아가야 한다

    w = b_world
    resp = w.convert(monkeypatch, B_KAKAO_ID)

    assert _query(resp).get("guest_merged") == ["false"] and "login_error" not in _query(resp)
    assert any(h.startswith("session=") for h in resp.headers.get_list("set-cookie"))   # 카카오 로그인은 성공
    assert db_session.get(User, w.guest_id).deleted_at is None
    assert w.owners() == _all_owned_by(w.guest_id)
    assert db_session.query(Membership).filter_by(map_id=w.map_id, user_id=w.guest_id).count() == 1
    assert db_session.query(Reaction).filter_by(user_id=w.guest_id).count() == 1

    me = w.guest.get("/auth/me")   # 응답 쿠키는 B 세션 — 로그인은 됐다
    assert me.status_code == 200 and me.json()["id"] == "user_b"
