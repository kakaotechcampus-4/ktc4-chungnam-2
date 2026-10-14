"""
탈퇴 연결 (#160, #155 결정) — 탈퇴하면 그 사람의 반응·근거 줄은 사라지고, 핀은 남으며 작성자
표시는 "탈퇴한 구성원"이 된다. 모듈 사이 이음새(auth → pins.api·recommend.api)라 여기서 검증한다.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from agent.models import AgentReasonSummary, AgentRun, AgentSuggestionView
from agent.tests import rows as agent_rows
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


TOOL_CALLS = [{"call_id": "t1", "tool": "get_reasons", "input": {"category": "음식점"},
               "result": [{"reaction_id": "r1", "type": "against", "text": "너무 매워요", "member_alias": "m2"}]}]
VERIFICATION = {"claims": [{"id": "c1", "kind": "quote", "text": "너무 매워요", "passed": True}]}


def _new_map(client, title):
    r = client.post("/maps", json={"title": title, "start_date": "2026-11-01", "end_date": "2026-11-03",
                                   "region": REGION})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_withdraw_clears_agent_data_of_the_maps_the_user_was_in(clients, db_session):
    """#512 — 탈퇴는 lock_member_maps가 잡은 지도 목록을 agent.api.delete_by_user에 넘긴다. 그 사람의 열람 기록은
    모두 지우고, 그 사람이 있던 지도(혼자라 함께 삭제되는 지도 포함)의 요약은 지우고 run의 도구 기록은 비운다.
    그 사람이 없던 지도는 그대로다."""
    a, b = clients
    shared = _new_map(a, "함께")
    token = a.post(f"/maps/{shared}/invite").json()["token"]
    assert b.post(f"/invites/{token}/accept").status_code == 200
    a_only = _new_map(a, "철수만")
    b_solo = _new_map(b, "영희만")   # 넘길 사람이 없어 탈퇴와 함께 삭제된다

    runs = {}
    for map_id in (shared, a_only, b_solo):
        runs[map_id] = agent_rows.run(db_session, map_id, tool_calls=TOOL_CALLS, verification=VERIFICATION,
                                      outcome="suggested").id
        agent_rows.summary(db_session, map_id)
    suggestion = agent_rows.suggestion(db_session, shared, run_id=runs[shared])
    agent_rows.view(db_session, suggestion.id, "user_a")
    agent_rows.view(db_session, suggestion.id, "user_b")
    db_session.commit()

    assert b.post("/auth/withdraw").status_code == 204

    db_session.expire_all()
    assert db_session.query(AgentSuggestionView.user_id).all() == [("user_a",)]
    assert [s.map_id for s in db_session.query(AgentReasonSummary).all()] == [a_only]
    for map_id in (shared, b_solo):
        run = db_session.get(AgentRun, runs[map_id])
        assert (run.tool_calls, run.verification, run.outcome) == ([], None, "suggested")   # 행과 지표는 남는다
    untouched = db_session.get(AgentRun, runs[a_only])
    assert (untouched.tool_calls, untouched.verification) == (TOOL_CALLS, VERIFICATION)
