"""
탈퇴 연결 (#160, #155 결정) — 탈퇴하면 그 사람의 반응·근거 줄은 사라지고, 핀은 남으며 작성자
표시는 "탈퇴한 구성원"이 된다. 모듈 사이 이음새(auth → pins.api·recommend.api)라 여기서 검증한다.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from auth.testing import session_cookie
from main import app  # noqa: F401  — 라우터 등록을 보장
from pins.models import Pin, Reaction
from recommend.models import EvidenceLine, RecommendRun

REGION = {"label": "부산", "lat": 35.1796, "lng": 129.0756}


@pytest.fixture()
def clients(app_client, two_users):
    a = TestClient(app_client.app, cookies=session_cookie("user_a"))
    b = TestClient(app_client.app, cookies=session_cookie("user_b"))
    yield a, b
    a.close()
    b.close()


def _pin(client, map_id, body):
    r = client.post(f"/maps/{map_id}/pins", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_withdraw_removes_reactions_and_evidence_lines_but_keeps_pins(clients, db_session, pin_body):
    a, b = clients
    map_id = a.post("/maps", json={"title": "부산", "start_date": "2026-11-01",
                                   "end_date": "2026-11-03", "region": REGION}).json()["id"]
    token = a.post(f"/maps/{map_id}/invite").json()["token"]
    assert b.post(f"/invites/{token}/accept").status_code == 200

    pin_a = _pin(a, map_id, pin_body("seongsu-kalguksu"))
    pin_b = _pin(b, map_id, pin_body("hongdae-ramen"))  # 탈퇴자가 찍은 핀
    for client in (a, b):
        for pin in (pin_a, pin_b):
            assert client.put(f"/pins/{pin}/reaction", json={"type": "like"}).status_code == 200

    run = RecommendRun(id=uuid.uuid4(), map_id=map_id, category="음식점", requested_by="user_a", status="done")
    db_session.add(run)
    db_session.flush()
    for author in ("user_a", "user_b"):
        db_session.add(EvidenceLine(run_id=run.id, author_id=author, source="manual", text="t", badge="preferred"))
    db_session.flush()

    assert b.post("/auth/withdraw").status_code == 204

    assert {r.user_id for r in db_session.query(Reaction).all()} == {"user_a"}
    assert [e.author_id for e in db_session.query(EvidenceLine).all()] == ["user_a"]
    assert db_session.query(Pin).count() == 2  # 핀은 남는다

    pins = {p["id"]: p for p in a.get(f"/maps/{map_id}/pins").json()}
    assert set(pins) == {pin_a, pin_b}
    assert pins[pin_b]["created_by_display_name"] == "탈퇴한 구성원"
    assert pins[pin_a]["created_by_display_name"] == "철수"
    # 남은 사람의 반응 조회는 탈퇴자를 싣지 않는다
    assert [r["display_name"] for r in a.get(f"/pins/{pin_b}/reactions").json()] == ["철수"]
