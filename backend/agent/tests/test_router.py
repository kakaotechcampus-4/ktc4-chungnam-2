"""agent 엔드포인트 5개(명세 14절, #531) — 실제 앱과 실제 멤버십으로 HTTP를 두드린다.

17절 12번(비구성원 404, accept·dismiss 경합 시 두 번째 409), 15번(shadow 제안은 응답과 이벤트에 없다), 렌더(실시간 핀
이름, 지워진 핀), 모드 끄고 켜기, has_unseen과 view 멱등. 요청은 자기 세션으로 커밋하므로 커밋하는 픽스처(world.py)를 쓴다.
"""

import threading
import uuid
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from agent import core, service
from agent.models import AgentCursor, AgentSettings, AgentSuggestion, AgentSuggestionView
from agent.tests.world import World, fake_places, real_now
from auth.testing import session_cookie
from common.database import get_db_session, session_scope
from places import api as places_api


@pytest.fixture()
def factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture()
def world(factory):
    w = World(factory, real_now())
    yield w
    w.cleanup()


@pytest.fixture()
def client(world):
    """사용자 이름을 받아 그 사람의 TestClient를 돌려준다. lifespan(dispatcher)은 띄우지 않는다."""
    from main import app

    def _db():
        with world.factory() as db, session_scope(db) as s:
            yield s

    app.dependency_overrides[get_db_session] = _db
    made = []

    def as_user(name: str) -> TestClient:
        c = TestClient(app, cookies=session_cookie(world.uid(name)))
        made.append(c)
        return c

    yield as_user
    for c in made:
        c.close()
    app.dependency_overrides.pop(get_db_session, None)


def suggest(world, map_id, *, diagnosis="category_gap", category="카페", ids=("p1", "p2"), shadow=False,
            expires_in=timedelta(hours=24)) -> str:
    """관찰의 저장 단계와 같은 함수(render_template, insert_suggestion)로 제안 하나를 넣는다."""
    sig = core.make_signal(diagnosis, category=category, evidence=[(i, "pin", world.now) for i in ids], features={})
    draft = core.render_template(sig) if diagnosis in ("no_reaction", "category_gap") else core.Draft(
        title="의견이 갈린 핀이 있어요", claims=[], advice=[], actions=[])
    with world.factory() as db:
        sid = service.insert_suggestion(db, map_id=map_id, run_id=None, signal=sig, draft=draft,
                                        now=world.now + expires_in - timedelta(hours=24), shadow=shadow)
        db.commit()
    return str(sid)


# ---------------------------------------------------------------- 상태와 has_unseen, view 멱등

def test_state_without_suggestion_defaults_to_on(world, client):
    map_id = world.map()

    body = client("u1").get(f"/maps/{map_id}/agent").json()

    assert body == {"settings": {"enabled": True, "updated_by": None, "updated_at": None},
                    "active_suggestion": None, "has_unseen": False, "summaries": []}


def test_has_unseen_is_per_member_and_view_is_idempotent(world, client):
    map_id = world.map()
    sid = suggest(world, map_id)
    u1, u2 = client("u1"), client("u2")

    state = u1.get(f"/maps/{map_id}/agent").json()
    assert state["has_unseen"] is True
    assert state["active_suggestion"]["title"] == "확정 리스트에 카페가 아직 없어요"
    assert state["active_suggestion"]["advice"] == [{"text": "확정 2곳 중 카페 0곳", "is_guess": False}]

    assert u1.post(f"/agent/suggestions/{sid}/view").status_code == 204
    assert u1.post(f"/agent/suggestions/{sid}/view").status_code == 204
    assert u1.get(f"/maps/{map_id}/agent").json()["has_unseen"] is False
    assert u2.get(f"/maps/{map_id}/agent").json()["has_unseen"] is True
    assert len(world.rows(AgentSuggestionView, suggestion_id=uuid.UUID(sid))) == 1
    assert world.agent_events(map_id) == []   # 열람은 이벤트가 없다


def test_view_of_resolved_suggestion_is_still_204(world, client):
    map_id = world.map()
    sid = suggest(world, map_id)
    assert client("u1").post(f"/agent/suggestions/{sid}/dismiss").status_code == 204

    assert client("u2").post(f"/agent/suggestions/{sid}/view").status_code == 204


def test_expired_by_time_is_not_shown_and_cannot_be_accepted(world, client):
    """만료 처리(관찰)가 오기 전이라도 expires_at이 지난 제안은 보이지 않고 수락하면 409다."""
    map_id = world.map()
    sid = suggest(world, map_id, expires_in=timedelta(seconds=-1))
    u1 = client("u1")

    assert u1.get(f"/maps/{map_id}/agent").json()["active_suggestion"] is None
    assert u1.post(f"/agent/suggestions/{sid}/accept", json={"action_index": 0}).status_code == 409


# ---------------------------------------------------------------- 렌더: 실시간 핀 이름, 지워진 핀

def test_render_uses_live_pin_query_and_drops_deleted_pin(world, client, monkeypatch):
    monkeypatch.setattr(places_api, "get_places", fake_places({"pl_a": "성수 칼국수", "pl_c": "온도 커피"}))
    map_id, (db_pin, live_pin, gone) = world.unseen_map(("db", "pl_a"), ("live", "성수 곱창"), ("db", "pl_c"))
    suggest(world, map_id, diagnosis="no_reaction", category=None, ids=(db_pin, live_pin, gone))
    world.delete_pin(gone)

    sug = client("u1").get(f"/maps/{map_id}/agent").json()["active_suggestion"]

    assert sug["title"] == "아직 확인되지 않은 핀이 3개 있어요"
    assert sorted(line["text"] for line in sug["advice"]) == ["성수 곱창", "성수 칼국수"]
    assert "온도 커피" not in str(sug)


# ---------------------------------------------------------------- accept, dismiss와 이벤트

def test_accept_returns_action_and_announces_resolved(world, client):
    map_id = world.map()
    sid = suggest(world, map_id)

    r = client("u2").post(f"/agent/suggestions/{sid}/accept", json={"action_index": 1})

    assert r.status_code == 200
    assert r.json() == {"action": {"index": 1, "type": "show_pins", "label": "카페 핀 보기",
                                   "params": {"category": "카페"}}}
    row = world.one(AgentSuggestion, map_id=map_id)
    assert (row.status, row.resolved_by, row.resolved_action) == ("accepted", world.uid("u2"),
                                                                    {"index": 1, "type": "show_pins"})
    assert world.agent_events(map_id) == [("agent.resolved", {
        "suggestion_id": sid, "status": "accepted", "resolved_action_type": "show_pins"})]   # resolved_by 없음


def test_action_index_out_of_range_is_422_and_changes_nothing(world, client):
    map_id = world.map()
    sid = suggest(world, map_id)

    r = client("u1").post(f"/agent/suggestions/{sid}/accept", json={"action_index": 2})

    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert world.one(AgentSuggestion, map_id=map_id).status == "active"


def test_second_resolve_is_409(world, client):
    map_id = world.map()
    sid = suggest(world, map_id)
    u1, u2 = client("u1"), client("u2")

    assert u1.post(f"/agent/suggestions/{sid}/dismiss").status_code == 204
    second = u2.post(f"/agent/suggestions/{sid}/accept", json={"action_index": 0})
    assert second.status_code == 409 and second.json()["code"] == "SUGGESTION_RESOLVED"
    assert u2.post(f"/agent/suggestions/{sid}/dismiss").status_code == 409
    assert world.agent_events(map_id) == [("agent.resolved", {
        "suggestion_id": sid, "status": "dismissed", "resolved_action_type": None})]


def test_concurrent_accept_and_dismiss_only_one_wins(world):
    """17절 12번 경합 — 가드 UPDATE가 앞 트랜잭션을 기다린 뒤 조건을 다시 보고 0행이 된다."""
    map_id = world.map()
    sid = uuid.UUID(suggest(world, map_id))
    with world.factory() as a:
        assert service.resolve_suggestion(a, sid, status="accepted", user_id="a", now=world.now,
                                          action={"index": 0, "type": "open_recommend"})
        result = []

        def second():
            with world.factory() as b:
                result.append(service.resolve_suggestion(b, sid, status="dismissed", user_id="b", now=world.now))
                b.commit()

        t = threading.Thread(target=second)
        t.start()
        t.join(0.5)
        assert t.is_alive()   # a가 커밋할 때까지 기다린다
        a.commit()
    t.join(10)

    assert result == [False]
    assert world.one(AgentSuggestion, map_id=map_id).status == "accepted"


# ---------------------------------------------------------------- 권한 (17절 12번)

def test_non_member_gets_404_everywhere(world, client):
    map_id = world.map(members=("u1", "u2"))
    world.map(members=("x1",))   # x1은 다른 지도의 구성원일 뿐이다
    sid = suggest(world, map_id)
    outsider = client("x1")

    assert outsider.get(f"/maps/{map_id}/agent").status_code == 404
    assert outsider.put(f"/maps/{map_id}/agent/settings", json={"enabled": False}).status_code == 404
    assert outsider.post(f"/agent/suggestions/{sid}/view").status_code == 404
    assert outsider.post(f"/agent/suggestions/{sid}/accept", json={"action_index": 0}).status_code == 404
    assert outsider.post(f"/agent/suggestions/{sid}/dismiss").status_code == 404
    assert world.one(AgentSuggestion, map_id=map_id).status == "active"


def test_unknown_suggestion_is_404(world, client):
    world.map()
    u1 = client("u1")
    assert u1.post("/agent/suggestions/not-a-uuid/view").status_code == 404
    assert u1.post(f"/agent/suggestions/{uuid.uuid4()}/dismiss").status_code == 404


# ---------------------------------------------------------------- shadow (17절 15번)

def test_shadow_suggestion_is_invisible(world, client):
    map_id = world.map()
    sid = suggest(world, map_id, diagnosis="split", category="음식점", shadow=True)
    u1 = client("u1")

    state = u1.get(f"/maps/{map_id}/agent").json()
    assert (state["active_suggestion"], state["has_unseen"]) == (None, False)
    assert u1.post(f"/agent/suggestions/{sid}/view").status_code == 404
    assert u1.post(f"/agent/suggestions/{sid}/accept", json={"action_index": 0}).status_code == 404
    assert u1.post(f"/agent/suggestions/{sid}/dismiss").status_code == 404
    assert world.one(AgentSuggestion, map_id=map_id).status == "active"
    assert world.agent_events(map_id) == []


# ---------------------------------------------------------------- 모드 끄고 켜기 (12.9)

def test_turning_off_supersedes_active_and_turning_on_wakes_cursor(world, client):
    map_id = world.map()
    sid = suggest(world, map_id)
    u1, u2 = client("u1"), client("u2")

    off = u2.put(f"/maps/{map_id}/agent/settings", json={"enabled": False})

    assert off.status_code == 200
    assert (off.json()["enabled"], off.json()["updated_by"]) == (False, world.uid("u2"))
    assert world.one(AgentSuggestion, map_id=map_id).status == "superseded"
    state = u1.get(f"/maps/{map_id}/agent").json()
    assert (state["settings"]["enabled"], state["active_suggestion"], state["has_unseen"]) == (False, None, False)
    assert world.agent_events(map_id) == [
        ("agent.resolved", {"suggestion_id": sid, "status": "superseded", "resolved_action_type": None}),
        ("agent.settings_changed", {"enabled": False, "updated_by": world.uid("u2")}),
    ]

    on = u1.put(f"/maps/{map_id}/agent/settings", json={"enabled": True})

    assert on.status_code == 200 and on.json()["enabled"] is True
    cursor = world.one(AgentCursor, map_id=map_id)
    assert cursor.next_check_at is not None and cursor.next_check_at >= world.now
    assert world.agent_events(map_id)[-1] == ("agent.settings_changed", {"enabled": True, "updated_by": world.uid("u1")})


def test_same_mode_writes_and_announces_nothing(world, client):
    map_id = world.map()

    r = client("u1").put(f"/maps/{map_id}/agent/settings", json={"enabled": True})

    assert r.json() == {"enabled": True, "updated_by": None, "updated_at": None}
    assert world.rows(AgentSettings, map_id=map_id) == []
    assert world.agent_events(map_id) == []


def test_turning_off_supersedes_shadow_without_event(world, client):
    map_id = world.map()
    suggest(world, map_id, diagnosis="split", category="음식점", shadow=True)

    client("u1").put(f"/maps/{map_id}/agent/settings", json={"enabled": False})

    assert world.one(AgentSuggestion, map_id=map_id).status == "superseded"
    assert [t for t, _ in world.agent_events(map_id)] == ["agent.settings_changed"]
