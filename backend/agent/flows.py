"""관찰 루프 — `run_tick`과 `observe_map`(docs/agent-v2.md 12.2, 12.4). 명령형 셸이다: 세션을 열고 닫고 순서를
지키며, 판단은 core(순수)에, 읽기와 쓰기는 snapshot과 service에 맡긴다.

- 요청 세션(get_db) 밖에서 돈다(12.6). 트랜잭션을 짧게 셋으로 나눈다 — ① 만료 정리 ② 스냅샷 읽기(REPEATABLE
  READ) ③ 재확인과 저장. 모델을 부를 M1에서도 ②와 ③ 사이에는 세션이 없다.
- 커밋은 `common.database.session_scope` 한 곳이다. 세션은 `session_factory`로 받는다(기본 SessionLocal, 테스트가
  테스트 DB로 바꾼다 — maps/purge.py와 같은 방식).

**M0(#515) 범위**: 모델 단계와 렌더를 건너뛴다. 1순위가 코드 유형(no_reaction, category_gap)이면 렌더 없는 초안을
저장하고, 모델 유형(stall, split)이면 침묵(outcome=silent)으로 기록한다. 우선순위는 늘 fallback_order다. 이벤트는
내지 않는다(agent.suggested, agent.resolved는 M1. shadow면 그때도 내지 않는다). 우리 조건 요약(8절)도 M1 이후다.

outcome(agent_runs.outcome)
- map_deleted: 지도가 삭제됐거나(#369) 정리까지 끝나 없음. 커서만 올리고 next_check_at은 비운다
- trip_ended: 여행 마지막 날(end_date)이 KST로 지남. 위와 같다
- no_signal: 탐지된 신호 없음
- blocked: 신호는 있지만 모두 정책에 막힘(12.3), 또는 저장하려는데 다른 관찰이 먼저 활성 제안을 넣음
- silent: 1순위가 모델 유형이라 M0에서는 제안을 만들지 않음(outcome_detail.skipped = "model_step")
- stale: 저장 직전 재확인(12.8)에서 신호가 사라졌거나 근거가 바뀜
- suggested: 제안을 저장함(shadow면 shadow=True)
저장 트랜잭션 맨 앞에서 지도가 삭제된 것을 보면(모델 호출 중 삭제 대역) 아무것도 쓰지 않는다 — agent_runs 행도 없다.
"""

import logging
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from agent import constants, core, service, snapshot
from agent.constants import CODE_TYPES, MODEL_TYPES, SUGGESTION_TTL, TICK_MAX_MAPS
from common.database import SessionLocal, session_scope
from maps import api as maps_api

log = logging.getLogger("pingo.agent")

SessionFactory = Callable[[], Session]


@contextmanager
def _write(factory: SessionFactory) -> Iterator[Session]:
    with factory() as db, session_scope(db) as s:
        yield s


@contextmanager
def _snapshot_read(factory: SessionFactory) -> Iterator[Session]:
    """REPEATABLE READ 읽기 트랜잭션(12.7) — 테이블 간 시점을 맞춘다. common을 고치지 않고 이 세션 연결에만 격리
    수준을 건다(연결이 풀로 돌아가면 SQLAlchemy가 원래 수준으로 되돌린다). 저장하지 않으므로 롤백으로 끝낸다."""
    with factory() as db:
        db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        try:
            yield db
        finally:
            db.rollback()


# ---------------------------------------------------------------- tick (12.2)

def run_tick(now: datetime, *, session_factory: SessionFactory = SessionLocal) -> list[str]:
    """지도를 골라(lease) 하나씩 관찰한다. 한 지도가 실패해도 다른 지도는 계속하고, lease는 늘 푼다. 관찰한
    map_id 목록을 돌려준다."""
    with _write(session_factory) as db:
        claims = service.claim_maps(db, now, limit=TICK_MAX_MAPS)
    for map_id, trigger in claims:
        try:
            observe_map(map_id, now, trigger=trigger, session_factory=session_factory)
        except Exception:
            log.exception("agent observe_map 실패 map_id=%s", map_id)
        finally:
            try:
                with _write(session_factory) as db:
                    service.release_lease(db, map_id)
            except Exception:   # 못 풀어도 LEASE_SEC 뒤에는 다른 실행이 가져간다(12.5)
                log.exception("agent release_lease 실패 map_id=%s", map_id)
    try:
        daily_cleanup_if_due(now, session_factory=session_factory)
    except Exception:
        log.exception("agent 보존 정리 실패")
    return [map_id for map_id, _ in claims]


_cleanup_done_on: date | None = None   # 이 프로세스가 보존 정리를 마친 KST 날짜


def daily_cleanup_if_due(now: datetime, *, session_factory: SessionFactory = SessionLocal) -> bool:
    """하루 한 번(KST) agent_runs 30일 초과분을 지운다(12.9). 했으면 True. 날짜는 프로세스 메모리에 둔다 — 인스턴스가
    여럿이거나 다시 뜨면 하루에 몇 번 돌 수 있지만 지우는 일이라 결과는 같다."""
    global _cleanup_done_on
    today = core.kst_date(now)
    if _cleanup_done_on == today:
        return False
    with _write(session_factory) as db:
        deleted = service.delete_old_runs(db, now)
    _cleanup_done_on = today
    log.info("agent 보존 정리: agent_runs %d행 삭제", deleted)
    return True


# ---------------------------------------------------------------- 관찰 (12.4)

def observe_map(
    map_id: str, now: datetime, *, trigger: str = "activity", session_factory: SessionFactory = SessionLocal,
) -> str | None:
    """지도 하나를 관찰하고 agent_runs에 남긴 outcome을 돌려준다. 저장 단계에서 지도가 삭제된 것을 보면 아무것도
    쓰지 않고 None(머리말의 outcome 목록)."""
    started = time.monotonic()

    def run_fields(snap: snapshot.Snapshot | None, outcome: str, **extra: Any) -> dict[str, Any]:
        return {
            "map_id": map_id, "started_at": now, "finished_at": now + timedelta(seconds=time.monotonic() - started),
            "trigger": trigger, "snapshot_at": now, "snapshot_seq": snap.latest_seq if snap else None,
            "used_model": False, "outcome": outcome, **extra,
        }

    # 1. 만료 정리 (짧은 쓰기). agent.resolved는 M1
    with _write(session_factory) as db:
        service.expire_suggestions(db, map_id, now)

    # 2. 스냅샷과 이력 (짧은 읽기, REPEATABLE READ). 여기서 세션을 닫는다
    with _snapshot_read(session_factory) as db:
        snap = snapshot.build(db, map_id, now)
        hist = service.load_history(db, map_id, now)

    ended = _ended(snap)
    if ended is not None:   # 끝난 지도는 관찰하지 않는다. 새 이벤트가 와야 다시 잡히고, 그때도 바로 끝난다
        with _write(session_factory) as db:
            service.insert_run(db, **run_fields(snap, ended))
            service.advance_cursor(db, map_id, snap.latest_seq if snap else None, next_check_at=None, observed_at=now)
        return ended

    # 3. 탐지와 활성 제안 무효화 판단 (순수)
    th = core.time_threshold(snap.action_times, snap.map.start_date, snap.today)
    signals = core.detect_all(snap, now, th)
    superseding = core.find_superseded(hist.active, signals)

    # 4. 정책 사전 검사, 5. 우선순위 (순수. M0은 fallback_order)
    passed, blocked = core.check_policy(signals, hist, snap, now, superseding=superseding)
    policy = core.load_policy()
    top, priority = core.choose_top(passed, policy)

    # 6. 초안 — M0은 렌더 없이 신호 그대로. 모델 유형이 1순위면 모델 단계를 건너뛰어 침묵한다
    draft = top if top is not None and top.diagnosis in CODE_TYPES else None
    outcome, detail = _planned_outcome(signals, top)

    # 7. 재확인과 저장 (짧은 쓰기 트랜잭션)
    with _write(session_factory) as db:
        if not maps_api.lock_map_if_alive(db, map_id):   # 지도 행 잠금 + 삭제 확인(#435, #512)
            return None                                   # 관찰 중 지도가 삭제됐다. 아무것도 쓰지 않는다
        if draft is not None and not _still_there(db, draft, map_id, now, th):
            draft, outcome = None, "stale"
        service.supersede(db, superseding, now)
        blocked_rows = [asdict(b) for b in blocked]
        run_id = service.insert_run(db, **run_fields(
            snap, outcome, signals=[core.signal_record(s) for s in signals], blocked=blocked_rows,
            priority=priority, policy_version=str(policy.version), outcome_detail=detail,
        ))
        new_expires_at = None
        if draft is not None:
            inserted = service.insert_suggestion(
                db, map_id=map_id, run_id=run_id, signal=draft, now=now, shadow=constants.AGENT_SHADOW_MODE,
            )
            if inserted is None:   # 다른 관찰이 먼저 활성 제안을 넣었다(부분 유니크 인덱스)
                outcome = "blocked"
                blocked_rows.append(asdict(core.Blocked(draft.id, "active_exists")))
                service.set_run_outcome(db, run_id, outcome, blocked=blocked_rows)
            else:
                new_expires_at = now + SUGGESTION_TTL
        # M1: shadow가 아니면 여기서 record_event(agent.suggested, agent.resolved)
        service.advance_cursor(
            db, map_id, snap.latest_seq, next_check_at=_next_check(snap, hist, now, th, new_expires_at),
            observed_at=now,
        )
    return outcome


def _ended(snap: snapshot.Snapshot | None) -> str | None:
    if snap is None or snap.map.deleted:
        return "map_deleted"
    if snap.today > snap.map.end_date:
        return "trip_ended"
    return None


def _planned_outcome(signals: list[core.Signal], top: core.Signal | None) -> tuple[str, dict[str, Any] | None]:
    """저장 단계 전의 outcome. 저장에서 stale이나 blocked(동시 저장)로 바뀔 수 있다."""
    if not signals:
        return "no_signal", None
    if top is None:
        return "blocked", None
    if top.diagnosis in MODEL_TYPES:
        return "silent", {"skipped": "model_step", "signal_id": top.id, "diagnosis": top.diagnosis}
    return "suggested", None


def _still_there(db: Session, draft: core.Signal, map_id: str, now: datetime, th: timedelta) -> bool:
    """상태 재확인(12.8) — 저장 트랜잭션 안에서 다시 읽은 사본으로 같은 탐지기를 돌린다. 기준 시간은 관찰 때 값을
    그대로 쓴다(재확인 사이에 기준이 움직여 신호가 깜빡이지 않게)."""
    fresh = snapshot.build(db, map_id, now)
    return fresh is not None and core.recheck(draft, fresh, now, th)


def _next_check(
    snap: snapshot.Snapshot, hist: core.History, now: datetime, th: timedelta, new_expires_at: datetime | None,
) -> datetime | None:
    """시간 기준이 가장 먼저 만료될 시각(12.4). 방금 넣은 제안의 만료도 후보다. 가장 최근 이벤트가 2초 안이면 지금으로
    당겨 다음 tick에 한 번 더 본다 — 그보다 작은 seq가 늦게 커밋됐어도 그 관찰에 들어간다(12.5)."""
    candidates = [t for t in (core.next_check_at(snap, hist, now, th), new_expires_at) if t is not None]
    if core.has_recent_event(snap.latest_event_at, now):
        candidates.append(now)
    return min(candidates) if candidates else None
