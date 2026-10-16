"""관찰 루프(#515, 명세 12.2~12.9) — run_tick, observe_map, 커서, lease, 기록, 정리.

17절 7(재확인으로 stale), 8(동시 저장에도 active 하나), 9(커서), 10(lease), 14(trip_ended, map_deleted, 관찰 중 삭제),
15(shadow면 이벤트 없음), 그리고 2절 13번(agent_* 어느 행에도 사유 글이 없음).

관찰은 자기 세션을 열고 커밋하므로 실제로 커밋하는 픽스처(world.py)를 쓴다.
"""

import json
import threading
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from agent import constants, core, flows, service
from agent.models import AgentCursor, AgentReasonSummary, AgentRun, AgentSettings, AgentSuggestion
from agent.schemas import AgentSuggestion as AgentSuggestionSchema
from agent.tests import rows
from agent.tests.world import World, fake_places, real_now
from maps import api as maps_api
from places import api as places_api

SECRET = "비밀사유_창가자리가좋아요"
SECRET_AGAINST = "비밀사유_너무시끄러워요"


@pytest.fixture()
def factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture()
def world(factory, monkeypatch):
    monkeypatch.setattr(flows, "TICK_MAX_MAPS", 1000)   # 같은 DB에 남은 다른 지도가 있어도 이 테스트 지도가 잡히게
    w = World(factory, real_now())
    yield w
    w.cleanup()


def tick(world, *, after=timedelta(0)):
    return flows.run_tick(world.now + after, session_factory=world.factory)


def observe(world, map_id, **kw):
    return flows.observe_map(map_id, world.now, session_factory=world.factory, **kw)


def _cursor(world, map_id) -> AgentCursor:
    return world.one(AgentCursor, map_id=map_id)


# ---------------------------------------------------------------- 기본 흐름, shadow (15)

def test_tick_saves_code_type_suggestion_and_emits_agent_suggested(world):
    """코드 유형은 shadow가 아니다(#531). 슬롯 문장과 claim으로 저장하고, 같은 트랜잭션에 렌더한 agent.suggested를 낸다."""
    map_id = world.gap_map()
    seq = world.event(map_id)

    assert map_id in tick(world)

    sug = world.one(AgentSuggestion, map_id=map_id)
    assert (sug.diagnosis, sug.category, sug.status, sug.shadow) == ("category_gap", "카페", "active", False)
    assert sug.title == "확정 리스트에 카페가 아직 없어요"
    assert sug.advice == [{"slot_text": "확정 {c1.value}곳 중 카페 {c2.value}곳", "is_guess": False}]
    assert [c["value"] for c in sug.claims] == [2, 0]
    assert sug.expires_at == world.now + constants.SUGGESTION_TTL
    run = world.one(AgentRun, map_id=map_id)
    # 신호가 둘이지만 순위는 코드 규칙이고 진단도 없다 — 모델 사용 없음(#582)
    assert (run.outcome, run.trigger, run.snapshot_seq, run.used_model) == ("suggested", "activity", seq, False)
    assert sug.run_id == run.id
    assert [s["diagnosis"] for s in run.signals] == ["category_gap", "category_gap"]
    assert run.priority == {"source": "rules", "final_order": ["s1", "s2"],
                            "fingerprints": [s["fingerprint"] for s in run.signals], "rule_hits": []}
    assert run.tool_calls == [] and run.verification is None
    [(type_, payload)] = world.agent_events(map_id)
    assert type_ == "agent.suggested"
    assert AgentSuggestionSchema.model_validate(payload).id == str(sug.id)
    assert payload["advice"] == [{"text": "확정 2곳 중 카페 0곳", "is_guess": False}]
    assert payload["actions"] == [
        {"index": 0, "type": "open_recommend", "label": "카페 추천 받기", "params": {"category": "카페"}},
        {"index": 1, "type": "show_pins", "label": "카페 핀 보기", "params": {"category": "카페"}},
    ]
    assert not {"claims", "fingerprint", "evidence_hash", "resolved_by", "shadow"} & set(payload)   # 서버 내부 값
    cur = _cursor(world, map_id)
    assert (cur.last_seen_seq, cur.lease_until, cur.next_check_at) == (seq, None, sug.expires_at)


def test_shadow_diagnosis_is_saved_without_events(world, monkeypatch):
    """17절 15번 — shadow 유형의 제안은 저장되지만 이벤트가 없다. #582부터 shadow 목록이 비어 있어 코드 유형을 넣어
    저장 경로를 본다."""
    monkeypatch.setattr(core, "SHADOW_DIAGNOSES", constants.CODE_TYPES)
    map_id = world.gap_map()
    world.event(map_id)

    tick(world)

    assert world.one(AgentSuggestion, map_id=map_id).shadow is True
    assert world.agent_events(map_id) == []


def test_all_types_are_exposed():
    """모델 유형도 #534 평가 뒤 노출한다(#582)."""
    assert constants.SHADOW_DIAGNOSES == ()
    assert [core.is_shadow(d) for d in ("stall", "split", "no_reaction", "category_gap")] == [False] * 4


def test_tick_max_maps_is_six():
    """관찰 최악 약 16초(#534) × 10이 lease 180초에 가까워 6으로(#582)."""
    assert constants.TICK_MAX_MAPS == 6


def test_no_reaction_suggestion_renders_pin_names(world, monkeypatch):
    """반응 공백(6.4) — 핀 이름은 저장하지 않고 이벤트를 만들 때 렌더한다. db 핀은 장소 이름, 실시간 핀은 검색어."""
    monkeypatch.setattr(places_api, "get_places", fake_places({"pl_a": "성수 칼국수"}))
    map_id, (db_pin, live_pin, _) = world.unseen_map(("db", "pl_a"), ("live", "성수 곱창"), ("db", "pl_b"))
    world.event(map_id)

    tick(world)

    sug = world.one(AgentSuggestion, map_id=map_id)
    assert sug.diagnosis == "no_reaction" and sug.title == "아직 확인되지 않은 핀이 {c1.value}개 있어요"
    assert "성수 칼국수" not in json.dumps(sug.advice + sug.claims, ensure_ascii=False)   # 이름은 저장하지 않는다
    [(_, payload)] = world.agent_events(map_id)
    assert payload["title"] == "아직 확인되지 않은 핀이 3개 있어요"
    # 장소 이름을 찾지 못한 핀(pl_b)은 지어내지 않고 줄을 뺀다
    assert sorted(line["text"] for line in payload["advice"]) == ["성수 곱창", "성수 칼국수"]
    [action] = payload["actions"]
    assert (action["type"], action["label"]) == ("show_pins", "미확인 핀 보기")
    assert db_pin in action["params"]["pin_ids"] and live_pin in action["params"]["pin_ids"]


def test_expired_and_superseded_announce_agent_resolved(world):
    """만료와 무효화도 agent.resolved를 낸다(15절). 누가 처리했는지는 싣지 않는다."""
    map_id = world.gap_map()
    world.event(map_id)
    tick(world)
    first = world.one(AgentSuggestion, map_id=map_id)

    world.confirm(map_id, world.pin(map_id, category="음식점"))   # 근거가 바뀐다 → superseded
    world.event(map_id)
    tick(world, after=timedelta(minutes=5))
    second = next(s for s in world.rows(AgentSuggestion, map_id=map_id) if s.status == "active")

    world.event(map_id)
    tick(world, after=constants.SUGGESTION_TTL + timedelta(minutes=10))   # 두 번째가 만료된다

    resolved = [p for t, p in world.agent_events(map_id) if t == "agent.resolved"]
    assert {"suggestion_id": str(first.id), "status": "superseded", "resolved_action_type": None} in resolved
    assert {"suggestion_id": str(second.id), "status": "expired", "resolved_action_type": None} in resolved


def test_shadow_suggestion_expires_without_event(world, factory):
    map_id = world.map()
    with factory() as db:
        rows.suggestion(db, map_id, shadow=True, expires_at=world.now - timedelta(minutes=1))
        db.commit()
    world.event(map_id)

    tick(world)

    assert world.one(AgentSuggestion, map_id=map_id).status == "expired"
    assert world.agent_events(map_id) == []


def test_own_event_reclaims_once_then_settles(world):
    """agent.suggested도 event_log seq를 올려 다음 tick에 그 지도를 한 번 더 관찰한다. 그 관찰은 활성 제안에 막혀
    (blocked) 이벤트를 내지 않으므로 그다음 tick에는 다시 잡히지 않는다."""
    map_id = world.gap_map()
    world.event(map_id)
    tick(world)

    assert map_id in tick(world, after=timedelta(minutes=5))
    assert map_id not in tick(world, after=timedelta(minutes=10))
    outcomes = [r.outcome for r in sorted(world.rows(AgentRun, map_id=map_id), key=lambda r: r.started_at)]
    assert outcomes == ["suggested", "blocked"]
    assert [t for t, _ in world.agent_events(map_id)] == ["agent.suggested"]


def test_mode_turned_off_during_observation_saves_nothing(world, monkeypatch):
    """관찰(읽기) 뒤 저장 전에 모드가 꺼지면 제안을 넣지 않는다 — blocked(mode_off). 모드 변경도 지도 행을 잠가
    저장과 줄을 선다."""
    map_id = world.gap_map()
    world.event(map_id)
    real_lock = maps_api.lock_map_if_alive

    def turn_off_then_lock(db, mid):
        with world.factory() as other:
            other.add(AgentSettings(map_id=map_id, enabled=False, updated_by=world.uid("u2")))
            other.commit()
        return real_lock(db, mid)

    monkeypatch.setattr(maps_api, "lock_map_if_alive", turn_off_then_lock)

    observe(world, map_id)

    run = world.one(AgentRun, map_id=map_id)
    assert run.outcome == "blocked" and {"signal_id": "s1", "reason": "mode_off"} in run.blocked
    assert world.rows(AgentSuggestion, map_id=map_id) == []
    assert world.agent_events(map_id) == []


def test_active_suggestion_blocks_until_superseded(world):
    """같은 상태로 다시 보면 활성 제안이 막고(blocked), 근거가 바뀌면 superseded가 되고 새 제안이 나온다(12.9)."""
    map_id = world.gap_map()
    world.event(map_id)
    tick(world)
    first = world.one(AgentSuggestion, map_id=map_id)

    world.event(map_id)
    tick(world, after=timedelta(minutes=5))
    runs = sorted(world.rows(AgentRun, map_id=map_id), key=lambda r: r.finished_at)
    assert runs[-1].outcome == "blocked"
    assert {b["reason"] for b in runs[-1].blocked} == {"active_exists"}

    world.confirm(map_id, world.pin(map_id, category="음식점"))   # 확정이 늘어 근거(evidence_hash)가 바뀐다
    world.event(map_id)
    tick(world, after=timedelta(minutes=10))

    by_id = {s.id: s for s in world.rows(AgentSuggestion, map_id=map_id)}
    assert by_id[first.id].status == "superseded"
    active = [s for s in by_id.values() if s.status == "active"]
    assert len(active) == 1 and active[0].id != first.id


def test_expired_suggestion_is_closed_at_observation_start(world):
    map_id = world.gap_map()
    world.event(map_id)
    tick(world)
    old = world.one(AgentSuggestion, map_id=map_id)

    world.event(map_id)
    tick(world, after=constants.SUGGESTION_TTL + timedelta(minutes=1))

    rows = world.rows(AgentSuggestion, map_id=map_id)
    assert {s.id: s.status for s in rows}[old.id] == "expired"
    # 만료는 사람이 닫은 것과 같아 같은 fingerprint(카페 공백)는 다시 내지 않고, 다음 신호(관광지 공백)가 나온다
    assert [s.category for s in rows if s.status == "active"] == ["관광지"]


def test_mode_off_map_is_not_claimed(world, factory):
    map_id = world.gap_map()
    world.event(map_id)
    with factory() as db:
        db.add(AgentSettings(map_id=map_id, enabled=False, updated_by=world.uid("u1")))
        db.commit()

    assert map_id not in tick(world)
    assert world.rows(AgentRun, map_id=map_id) == []


def test_no_signal_outcome(world):
    map_id = world.map()
    world.event(map_id)

    tick(world)

    run = world.one(AgentRun, map_id=map_id)
    assert (run.outcome, run.signals, run.priority) == ("no_signal", [], None)


# ---------------------------------------------------------------- 7. 재확인으로 stale

def test_state_change_before_save_makes_it_stale(world, monkeypatch):
    """관찰(읽기) 뒤 저장 전에 카페가 확정되면 카페 공백 초안을 버린다 — outcome=stale, 제안 없음."""
    map_id = world.gap_map()
    cafe = world.pin(map_id, category="카페")
    world.event(map_id)
    real_lock = maps_api.lock_map_if_alive

    def confirm_then_lock(db, mid):
        world.confirm(map_id, cafe, hours_ago=0)   # 다른 연결에서 커밋(모델 호출 중 일어난 변화 대역)
        return real_lock(db, mid)

    monkeypatch.setattr(maps_api, "lock_map_if_alive", confirm_then_lock)

    tick(world)

    assert world.one(AgentRun, map_id=map_id).outcome == "stale"
    assert world.rows(AgentSuggestion, map_id=map_id) == []
    assert _cursor(world, map_id).last_seen_seq > 0   # stale도 관찰은 끝났으니 커서는 오른다


# ---------------------------------------------------------------- 8. 동시 저장에도 active 하나

def test_two_concurrent_saves_leave_one_active(world, monkeypatch):
    """두 관찰이 같은 상태를 읽고 동시에 저장하러 와도 active는 하나다. 늦은 쪽은 blocked(active_exists)로 남는다."""
    map_id = world.gap_map()
    world.event(map_id)
    with world.factory() as db:
        db.add(AgentCursor(map_id=map_id))
        db.commit()
    barrier = threading.Barrier(2, timeout=10)
    real_lock = maps_api.lock_map_if_alive

    def lock_together(db, mid):
        barrier.wait()   # 둘 다 스냅샷을 읽은 뒤에야 저장으로 들어간다
        return real_lock(db, mid)

    monkeypatch.setattr(maps_api, "lock_map_if_alive", lock_together)
    outcomes = []
    threads = [threading.Thread(target=lambda: outcomes.append(observe(world, map_id))) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)

    assert sorted(outcomes) == ["blocked", "suggested"]
    assert len([s for s in world.rows(AgentSuggestion, map_id=map_id) if s.status == "active"]) == 1
    blocked = next(r for r in world.rows(AgentRun, map_id=map_id) if r.outcome == "blocked")
    assert {"signal_id": "s1", "reason": "active_exists"} in blocked.blocked


def test_insert_suggestion_conflict_returns_none(world):
    """부분 유니크 인덱스 — 커밋 전 활성 제안이 있으면 두 번째 insert는 기다렸다가 아무것도 넣지 않는다."""
    map_id = world.map()
    sig = core.make_signal("category_gap", category="카페", evidence=[("p1", "confirmed", world.now)], features={})
    draft = core.render_template(sig)
    with world.factory() as a:
        run_a = service.insert_run(a, map_id=map_id, started_at=world.now, trigger="time", outcome="suggested")
        assert service.insert_suggestion(
            a, map_id=map_id, run_id=run_a, signal=sig, draft=draft, now=world.now, shadow=True)
        result = []

        def second():
            with world.factory() as b:
                run_b = service.insert_run(b, map_id=map_id, started_at=world.now, trigger="time", outcome="x")
                result.append(service.insert_suggestion(
                    b, map_id=map_id, run_id=run_b, signal=sig, draft=draft, now=world.now, shadow=True))
                b.commit()

        t = threading.Thread(target=second)
        t.start()
        t.join(0.5)
        assert t.is_alive()   # a가 커밋할 때까지 기다린다
        a.commit()
    t.join(10)

    assert result == [None]
    assert len(world.rows(AgentSuggestion, map_id=map_id)) == 1


# ---------------------------------------------------------------- 9. 커서

def test_cursor_is_max_seq_and_gaps_from_other_maps_do_not_reclaim(world):
    """다른 지도 이벤트가 사이사이 끼어 이 지도의 seq에 빈 번호가 있어도, 관찰 뒤 커서는 가장 큰 seq이고 다음 tick에
    다시 잡히지 않는다(#525). 신호가 없는 지도를 쓴다 — 제안이 나오면 agent.suggested가 seq를 올려 한 번 더 잡힌다
    (test_own_event_reclaims_once_then_settles)."""
    a, b = world.map(), world.map()
    world.event(a)
    world.event(b)
    world.event(a)
    world.event(b)
    last_a = world.event(a)
    last_b = world.event(b)

    assert {a, b} <= set(tick(world))
    assert (_cursor(world, a).last_seen_seq, _cursor(world, b).last_seen_seq) == (last_a, last_b)

    again = tick(world, after=timedelta(minutes=5))

    assert a not in again and b not in again


def test_new_event_reclaims_with_activity_trigger(world):
    map_id = world.gap_map()
    world.event(map_id)
    tick(world)
    later = world.event(map_id)

    assert map_id in tick(world, after=timedelta(minutes=5))
    assert _cursor(world, map_id).last_seen_seq == later


def test_recent_event_pulls_next_check_to_now(world):
    """가장 최근 이벤트가 2초 안이면 next_check_at = 지금. 다음 tick에 한 번 더 관찰한다(12.5 보완). 신호가 없는
    지도라 agent 이벤트도 없다."""
    map_id = world.map()
    world.event(map_id, seconds_ago=1)

    tick(world)

    assert _cursor(world, map_id).next_check_at == world.now
    assert map_id in tick(world)   # 새 이벤트가 없어도 시간 점검으로 다시 잡힌다
    assert sorted(r.trigger for r in world.rows(AgentRun, map_id=map_id)) == ["activity", "time"]


def test_old_event_does_not_pull_next_check(world):
    map_id = world.gap_map()
    world.event(map_id, seconds_ago=3)

    tick(world)

    assert _cursor(world, map_id).next_check_at == world.now + constants.SUGGESTION_TTL


def test_rolled_back_save_keeps_cursor(world, monkeypatch):
    """저장 트랜잭션이 실패하면 커서도 그대로다. 실패는 로그로 남고 lease는 풀린다."""
    map_id = world.gap_map()
    world.event(map_id)

    def boom(db, **fields):
        raise RuntimeError("저장 실패")

    monkeypatch.setattr(service, "insert_run", boom)

    tick(world)

    cur = _cursor(world, map_id)
    assert (cur.last_seen_seq, cur.next_check_at, cur.lease_until) == (0, None, None)
    assert world.rows(AgentSuggestion, map_id=map_id) == []


def test_one_failing_map_does_not_stop_others(world, monkeypatch):
    bad, good = world.gap_map(), world.gap_map()
    world.event(bad)
    world.event(good)
    real_observe = flows.observe_map

    def observe_or_fail(map_id, now, **kw):
        if map_id == bad:
            raise RuntimeError("관찰 실패")
        return real_observe(map_id, now, **kw)

    monkeypatch.setattr(flows, "observe_map", observe_or_fail)

    tick(world)

    assert world.one(AgentRun, map_id=good).outcome == "suggested"
    assert _cursor(world, bad).lease_until is None and _cursor(world, good).lease_until is None


# ---------------------------------------------------------------- 10. lease

def test_two_concurrent_ticks_observe_each_map_once(world):
    maps = [world.gap_map() for _ in range(3)]
    for m in maps:
        world.event(m)
    barrier = threading.Barrier(2, timeout=10)
    claimed = []

    def run():
        barrier.wait()
        claimed.append(tick(world))

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    ours = [m for got in claimed for m in got if m in maps]
    assert sorted(ours) == sorted(maps)
    for m in maps:
        assert len(world.rows(AgentRun, map_id=m)) == 1


def test_locked_and_leased_cursor_is_skipped(world):
    """한 실행이 잠근 커서는 SKIP LOCKED로 건너뛰고, 커밋된 lease가 살아 있는 동안에도 잡지 않는다."""
    map_id = world.gap_map()
    world.event(map_id)
    with world.factory() as p:   # 커서 행을 미리 만들어 둔다 — 아래 a의 미커밋 upsert를 b가 기다리지 않게
        for m, _ in service.claim_maps(p, world.now, limit=1000):
            service.release_lease(p, m)
        p.commit()
    with world.factory() as a, world.factory() as b:
        assert [m for m, _ in service.claim_maps(a, world.now, limit=1000) if m == map_id] == [map_id]
        assert map_id not in [m for m, _ in service.claim_maps(b, world.now, limit=1000)]   # 잠김
        b.rollback()
        a.commit()
        assert map_id not in [m for m, _ in service.claim_maps(b, world.now, limit=1000)]   # lease
        b.rollback()
        later = world.now + timedelta(seconds=constants.LEASE_SEC + 1)
        assert map_id in [m for m, _ in service.claim_maps(b, later, limit=1000)]   # lease가 지나면 다시
        b.rollback()


# ---------------------------------------------------------------- 14. 여행 종료, 지도 삭제

def test_trip_ended_map_only_advances_cursor(world):
    map_id = world.gap_map(start=world.today - timedelta(days=3), end=world.today - timedelta(days=1))
    seq = world.event(map_id)

    tick(world)

    run = world.one(AgentRun, map_id=map_id)
    assert (run.outcome, run.signals, run.snapshot_seq) == ("trip_ended", [], seq)
    assert world.rows(AgentSuggestion, map_id=map_id) == []
    cur = _cursor(world, map_id)
    assert (cur.last_seen_seq, cur.next_check_at) == (seq, None)


def test_last_trip_day_is_still_observed(world):
    map_id = world.gap_map(start=world.today - timedelta(days=2), end=world.today)
    world.event(map_id)

    tick(world)

    assert world.one(AgentRun, map_id=map_id).outcome == "suggested"


def test_deleted_map_ends_with_map_deleted(world):
    map_id = world.gap_map(deleted=True)
    seq = world.event(map_id)

    tick(world)

    assert world.one(AgentRun, map_id=map_id).outcome == "map_deleted"
    assert world.rows(AgentSuggestion, map_id=map_id) == []
    assert (_cursor(world, map_id).last_seen_seq, _cursor(world, map_id).next_check_at) == (seq, None)


def test_missing_map_ends_with_map_deleted(world):
    """지도 행이 없으면(정리까지 끝남, build가 None) map_deleted로 끝난다."""
    ghost = f"ghost_{uuid.uuid4().hex[:8]}"
    world.map_ids.append(ghost)   # 정리 대상에 올린다
    world.event(ghost)

    tick(world)

    assert world.one(AgentRun, map_id=ghost).outcome == "map_deleted"


def test_map_deleted_during_observation_writes_nothing(world, monkeypatch):
    """모델 호출 중 삭제 대역 — 저장 트랜잭션 맨 앞 lock_map_if_alive가 False면 run도 제안도 커서도 쓰지 않는다."""
    map_id = world.gap_map()
    world.event(map_id)
    real_lock = maps_api.lock_map_if_alive

    def delete_then_lock(db, mid):
        world.delete_map(map_id)
        return real_lock(db, mid)

    monkeypatch.setattr(maps_api, "lock_map_if_alive", delete_then_lock)

    tick(world)

    assert world.rows(AgentRun, map_id=map_id) == []
    assert world.rows(AgentSuggestion, map_id=map_id) == []
    cur = _cursor(world, map_id)
    assert (cur.last_seen_seq, cur.lease_until) == (0, None)


# ---------------------------------------------------------------- 2절 13번: 사유 글을 저장하지 않는다

def test_no_agent_row_contains_reason_text(world, factory):
    """사유가 달린 ♥와 🚫가 있는 지도를 관찰한 뒤 agent_* 어느 행의 직렬화에도 사유 글이 없다. 정체(stall)가
    1순위라 진단 스텁이 get_reasons를 부르고(결과에 사유 글이 있다) silent로 끝난다 — 도구 기록에는 글 대신 글자 수만
    남는다(10절, 2절 13번). 관찰 끝에 요약도 만든다(#586, 17절 16번 — 요약을 거친 뒤에도 글이 없다)."""
    map_id = world.gap_map()
    food = world.pin(map_id, category="음식점", by="u1")
    cafe = world.pin(map_id, category="카페", by="u1")
    world.react(food, "u2", "like", hours_ago=20, text=SECRET)
    against = world.react(cafe, "u3", "against", hours_ago=20, text=SECRET_AGAINST)
    world.event(map_id)

    tick(world)

    assert world.one(AgentRun, map_id=map_id, trigger="summary").outcome == "summarized"
    assert world.rows(AgentReasonSummary, map_id=map_id)
    run = world.one(AgentRun, map_id=map_id, trigger="activity")
    assert run.outcome == "silent"
    assert run.outcome_detail == {"signal_id": "s1", "diagnosis": "stall", "decision": "silent"}
    assert against in run.signals[0]["evidence_ids"]   # 근거는 reaction_id로만
    [call] = run.tool_calls
    assert call["name"] == "get_reasons" and call["call_id"] == "t1"
    [reason] = [r for r in call["result"]["reasons"] if r["reaction_id"] == against]
    assert reason["text_len"] == len(SECRET_AGAINST) and "text" not in reason
    with factory() as db:
        for table in ("agent_runs", "agent_suggestions", "agent_cursors", "agent_suggestion_views",
                      "agent_reason_summaries", "agent_run_advice", "agent_settings"):
            dumped = json.dumps(
                db.execute(text(f"SELECT row_to_json(t)::text FROM {table} t")).scalars().all(), ensure_ascii=False
            )
            assert SECRET not in dumped and SECRET_AGAINST not in dumped, table


# ---------------------------------------------------------------- 보존 정리 (12.9)

def test_daily_cleanup_deletes_old_runs_once_a_day(world, monkeypatch):
    monkeypatch.setattr(flows, "_cleanup_done_on", None)
    map_id = world.map()
    with world.factory() as db:
        old = service.insert_run(db, map_id=map_id, started_at=world.now - timedelta(days=31), trigger="time",
                                 outcome="no_signal")
        recent = service.insert_run(db, map_id=map_id, started_at=world.now - timedelta(days=29), trigger="time",
                                    outcome="no_signal")
        db.commit()

    assert flows.daily_cleanup_if_due(world.now, session_factory=world.factory) is True
    assert {r.id for r in world.rows(AgentRun, map_id=map_id)} == {recent}
    assert old not in {r.id for r in world.rows(AgentRun, map_id=map_id)}
    assert flows.daily_cleanup_if_due(world.now + timedelta(minutes=5), session_factory=world.factory) is False
