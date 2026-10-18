"""관찰 루프 — `run_tick`과 `observe_map`(docs/agent-v2.md 12.2, 12.4). 명령형 셸이다: 세션을 열고 닫고 순서를
지키며, 판단은 core(순수)에, 읽기와 쓰기는 snapshot과 service에 맡긴다.

- 요청 세션(get_db) 밖에서 돈다(12.6). 트랜잭션을 짧게 셋으로 나눈다 — ① 만료 정리 ② 스냅샷 읽기(REPEATABLE
  READ) ③ 재확인과 저장. 모델 호출(진단)은 ②와 ③ 사이에 하고 그동안 세션이 없다. 도구는 자기 읽기 세션을
  짧게 열고 닫는다(tools.py).
- 커밋은 `common.database.session_scope` 한 곳이다. 세션은 `session_factory`로 받는다(기본 SessionLocal, 테스트가
  테스트 DB로 바꾼다 — maps/purge.py와 같은 방식).

**M1 범위(#533, #582)**: 우선순위는 코드 규칙이다(core.choose_top, 7절) — 모델을 부르지 않는다. 1순위가 코드 유형
(no_reaction, category_gap)이면 템플릿 초안(core.render_template), 모델 유형(stall, split)이면 진단(llm.agent_diagnose,
도구는 tools.py)을 부르고 core.verify_diagnosis를 통과한 것만 초안이 된다. 모델은 Gateway(deps.py)가 고른다 — dev는
고정 응답 스텁이다. 모델 사용 1회(used_model, 3절)는 진단을 부른 관찰이다. shadow는 유형별이다
(constants.SHADOW_DIAGNOSES — #582부터 비어 있어 모든 유형이 나간다) — shadow가 아닌 제안만 이벤트를 낸다: 저장
(agent.suggested), 만료와 무효화(agent.resolved).

**우리 조건 요약(8절, #586)**: 관찰 끝(12.4 8단계)에서 `update_summary`가 카테고리 하나를 갱신한다. 지도 제안과 별도
트랜잭션, 별도 agent_runs 행(trigger=summary, outcome=summarized)이다. 칸 나누기는 core, 근거 줄은 tools(②와 #422),
문구는 고정이라 모델 사용으로 세지 않는다(used_model=false). 갱신하면 같은 트랜잭션에 agent.summary_updated를 낸다.

**추천 막힘 조언(9절, #587)**: `advise_run`. AI 추천 결과 화면의 `GET /runs/{runId}/advice`(agent/router.py)가 부른다. 관찰과
따로 돌고(요청 안), 읽기 → 모델(세션 없음) → 쓰기를 짧은 세션으로 나눈다. run당 한 번 저장한다(trigger=run_advice).

화면 요청(명세 14절)도 여기 있다 — `get_state`, `change_settings`, `view`, `accept`, `dismiss`. 요청 세션(get_db) 안에서
돌고 커밋은 그 세션이 한다. 이벤트는 같은 트랜잭션에 `record_event`로 남긴다. 권한은 router가 authz.guard로 끝낸 뒤다.

outcome(agent_runs.outcome)
- map_deleted: 지도가 삭제됐거나(#369) 정리까지 끝나 없음. 커서만 올리고 next_check_at은 비운다
- trip_ended: 여행 마지막 날(end_date)이 KST로 지남. 위와 같다
- no_signal: 탐지된 신호 없음
- blocked: 신호는 있지만 모두 정책에 막힘(12.3), 또는 저장하려는데 다른 관찰이 먼저 활성 제안을 넣음
- silent, unknown: 진단 모델이 침묵을 골랐다(decision). outcome_detail에 signal_id, diagnosis, decision
- invalid_schema: 진단 응답이 스키마에 맞지 않음(AgentCallFailed reason=invalid_schema). 재요청하지 않는다
- model_failed: 진단 호출 실패나 타임아웃(AgentCallFailed reason=call_failed|timeout). 이유는 outcome_detail
- invalid_claims: 검증(11.2) 2단계(신호 불일치)나 7단계(성립 실패)에서 떨어짐. 내역은 verification
- stale: 저장 직전 재확인(12.8)에서 신호가 사라졌거나 근거가 바뀜
- suggested: 제안을 저장함(shadow 유형이면 shadow=True)
요약 관찰(trigger=summary)의 outcome
- summarized: 그 카테고리 요약을 덮어씀. outcome_detail은 {category}
- model_failed: ②(사유 구조화)가 실패해 요약을 만들지 못함. 요약은 그대로 두고 다음 관찰에서 다시 본다
저장 트랜잭션 맨 앞에서 지도가 삭제된 것을 보면(모델 호출 중 삭제 대역) 아무것도 쓰지 않는다 — agent_runs 행도 없다.
"""

import logging
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from agent import core, deps, service, snapshot, tools
from agent.constants import CODE_TYPES, SUGGESTION_TTL, TICK_MAX_MAPS
from agent.models import AgentSuggestion as SuggestionRow
from agent.schemas import (
    AgentAcceptResponse,
    AgentCallFailed,
    AgentSettings,
    AgentState,
    AgentSuggestion,
    AgentSummary,
    AgentUsage,
    RunAdvice,
)
from auth import api as auth_api
from common import categories
from common.database import SessionLocal, session_scope
from common.errors import AppError
from common.events import record_event
from llm import api as llm_api
from maps import api as maps_api
from pins import api as pins_api
from places import api as places_api
from recommend import api as recommend_api

log = logging.getLogger("pingo.agent")

SessionFactory = Callable[[], Session]


@contextmanager
def _write(factory: SessionFactory) -> Iterator[Session]:
    with factory() as db, session_scope(db) as s:
        yield s


@contextmanager
def _short_read(factory: SessionFactory) -> Iterator[Session]:
    """짧은 읽기 세션(12.6). 쓰지 않으므로 롤백으로 닫는다."""
    with factory() as db:
        try:
            yield db
        finally:
            db.rollback()


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

def run_tick(
    now: datetime, *, session_factory: SessionFactory = SessionLocal, gateway: deps.AgentLlmGateway | None = None,
) -> list[str]:
    """지도를 골라(lease) 하나씩 관찰한다. 한 지도가 실패해도 다른 지도는 계속하고, lease는 늘 푼다. 관찰한
    map_id 목록을 돌려준다. gateway가 없으면 deps.get_llm_gateway()(LLM_MODE로 고른 것)."""
    gateway = gateway or deps.get_llm_gateway()
    with _write(session_factory) as db:
        claims = service.claim_maps(db, now, limit=TICK_MAX_MAPS)
    for map_id, trigger in claims:
        try:
            observe_map(map_id, now, trigger=trigger, session_factory=session_factory, gateway=gateway)
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
    gateway: deps.AgentLlmGateway | None = None,
) -> str | None:
    """지도 하나를 관찰하고 agent_runs에 남긴 outcome을 돌려준다. 저장 단계에서 지도가 삭제된 것을 보면 아무것도
    쓰지 않고 None(머리말의 outcome 목록)."""
    started = time.monotonic()
    gateway = gateway or deps.get_llm_gateway()

    def run_fields(snap: snapshot.Snapshot | None, outcome: str, **extra: Any) -> dict[str, Any]:
        return {
            "map_id": map_id, "started_at": now, "finished_at": now + timedelta(seconds=time.monotonic() - started),
            "trigger": trigger, "snapshot_at": now, "snapshot_seq": snap.latest_seq if snap else None,
            "used_model": False, "outcome": outcome, **extra,
        }

    # 1. 만료 정리 (짧은 쓰기) + agent.resolved
    with _write(session_factory) as db:
        _announce_resolved(db, map_id, service.expire_suggestions(db, map_id, now), "expired")

    # 2. 스냅샷과 이력 (짧은 읽기, REPEATABLE READ). 여기서 세션을 닫는다
    with _snapshot_read(session_factory) as db:
        snap = snapshot.build(db, map_id, now)
        hist = service.load_history(db, map_id, now)
        # 검증(11.2 5단계)이 문장에서 찾는 표시 이름. 모델에는 가지 않는다
        names = list(auth_api.display_names(db, [m.user_id for m in snap.members]).values()) if snap else []

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

    # 4. 정책 사전 검사 (순수)
    passed, blocked = core.check_policy(signals, hist, snap, now, superseding=superseding)

    # 5. 우선순위 — 코드 규칙(7절, #582). 모델을 부르지 않는다
    policy = core.load_policy()
    top, priority = core.choose_top(passed, policy)

    # 6. 초안 — 코드 유형은 템플릿, 모델 유형은 진단과 검증(세션 없음, 도구만 짧게 읽는다)
    step = _draft(map_id, top, snap, names, now, session_factory, gateway) if top is not None else _Step(None)
    chosen = top if step.draft is not None else None
    draft = step.draft
    outcome, detail = _planned_outcome(signals, top, step)
    usages = [step.usage] if step.usage is not None else []

    # 7. 재확인과 저장 (짧은 쓰기 트랜잭션). 이벤트도 같은 트랜잭션
    with _write(session_factory) as db:
        if not maps_api.lock_map_if_alive(db, map_id):   # 지도 행 잠금 + 삭제 확인(#435, #512)
            return None                                   # 관찰 중 지도가 삭제됐다. 아무것도 쓰지 않는다
        if chosen is not None and not _still_there(db, chosen, map_id, now, th):
            chosen, draft, outcome = None, None, "stale"
        mode_off = chosen is not None and not core.settings_view(service.get_settings(db, map_id)).enabled
        if mode_off:   # 관찰 중 모드가 꺼졌다. change_settings도 지도 행을 잠가서 둘은 줄을 선다
            blocked.append(core.Blocked(chosen.id, "mode_off"))
            chosen, draft, outcome = None, None, "blocked"
        _announce_resolved(db, map_id, service.supersede(db, superseding, now), "superseded")
        blocked_rows = [asdict(b) for b in blocked]
        run_id = service.insert_run(db, **run_fields(
            snap, outcome, signals=[core.signal_record(s) for s in signals], blocked=blocked_rows,
            priority=priority, policy_version=str(policy.version), outcome_detail=detail,
            used_model=step.used_model, tool_calls=step.tool_calls, verification=step.verification,
            **core.model_usage(usages),
        ))
        new_expires_at = None
        if chosen is not None:
            shadow = core.is_shadow(chosen.diagnosis)
            inserted = service.insert_suggestion(
                db, map_id=map_id, run_id=run_id, signal=chosen, draft=draft, now=now, shadow=shadow,
            )
            if inserted is None:   # 다른 관찰이 먼저 활성 제안을 넣었다(부분 유니크 인덱스)
                outcome = "blocked"
                blocked_rows.append(asdict(core.Blocked(chosen.id, "active_exists")))
                service.set_run_outcome(db, run_id, outcome, blocked=blocked_rows)
            else:
                new_expires_at = now + SUGGESTION_TTL
                if not shadow:
                    _announce_suggested(db, map_id, inserted)
        service.advance_cursor(
            db, map_id, snap.latest_seq, next_check_at=_next_check(snap, hist, now, th, new_expires_at),
            observed_at=now,
        )

    # 8. 요약 (별도 흐름, 별도 트랜잭션)
    update_summary(map_id, snap, hist, now, session_factory=session_factory, gateway=gateway)
    return outcome


def _ended(snap: snapshot.Snapshot | None) -> str | None:
    if snap is None or snap.map.deleted:
        return "map_deleted"
    if snap.today > snap.map.end_date:
        return "trip_ended"
    return None


@dataclass(frozen=True)
class _Step:
    """6단계 결과. outcome이 None이면 초안이 있다(suggested) — 코드 유형이거나 검증을 통과한 진단."""
    draft: core.Draft | None
    outcome: str | None = None
    detail: dict[str, Any] | None = None
    used_model: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] | None = None
    usage: AgentUsage | None = None   # 진단 호출의 사용량(#564). 코드 유형은 None


def _draft(
    map_id: str, top: core.Signal, snap: snapshot.Snapshot, names: list[str], now: datetime,
    session_factory: SessionFactory, gateway: deps.AgentLlmGateway,
) -> _Step:
    """제안 초안(12.4 6단계). 코드 유형은 템플릿. 모델 유형은 진단을 부른다 — split은 충돌 종류(compare_reasons, 코드)를
    먼저 계산해 입력에 넣는다. 실패(AgentCallFailed)와 검증 실패는 재요청하지 않고 침묵한다(2절 10번)."""
    if top.diagnosis in CODE_TYPES:
        return _Step(core.render_template(top))
    ctx = tools.ToolContext(
        map_id=map_id, snap=snap, allowed=llm_api.DIAGNOSIS_TOOLS[top.diagnosis], session_factory=session_factory,
        structure=gateway.structure, now=now,
    )
    comparison = _comparison(ctx, top)
    reply = gateway.diagnose(core.diagnosis_input(top, snap, comparison), tool_runner=ctx.run)
    out = reply.result
    which = {"signal_id": top.id, "diagnosis": top.diagnosis}
    if isinstance(out, AgentCallFailed):
        return _Step(None, core.failed_outcome(out.reason), which | {"reason": out.reason, "detail": out.detail},
                     used_model=True, tool_calls=ctx.calls, usage=reply.usage)
    verified = core.verify_diagnosis(out, top, snap, ctx.results, member_names=names, comparison=comparison)
    outcome = None if verified.draft is not None else verified.outcome
    return _Step(verified.draft, outcome, None if outcome is None else which | {"decision": out.decision},
                 used_model=True, tool_calls=ctx.calls, verification=verified.record, usage=reply.usage)


def _comparison(ctx: tools.ToolContext, top: core.Signal) -> dict[str, Any] | None:
    """split의 충돌 종류(6.3). ②가 실패하면 없이 진단한다(모델은 compare_reasons 도구로 다시 볼 수 있다)."""
    if top.diagnosis != "split":
        return None
    try:
        return tools.comparison(ctx, pin_id=top.pin_id)
    except llm_api.PlanEvidenceFailed:
        log.warning("agent compare_reasons 실패(②) map_id=%s", ctx.map_id)
        return None


def _planned_outcome(
    signals: list[core.Signal], top: core.Signal | None, step: _Step,
) -> tuple[str, dict[str, Any] | None]:
    """저장 단계 전의 outcome. 저장에서 stale이나 blocked(동시 저장)로 바뀔 수 있다."""
    if not signals:
        return "no_signal", None
    if top is None:
        return "blocked", None
    if step.outcome is not None:
        return step.outcome, step.detail
    return "suggested", None


def _announce_resolved(db: Session, map_id: str, changed: service.Changed, status: str) -> None:
    """상태를 바꾼 제안 중 shadow가 아닌 것만 agent.resolved를 낸다(15절)."""
    for suggestion_id, shadow in changed:
        if not shadow:
            record_event(db, core.resolved_event(map_id, suggestion_id, status))


def _announce_suggested(db: Session, map_id: str, suggestion_id) -> None:
    """방금 넣은 제안을 렌더해 agent.suggested로 낸다. 렌더는 같은 트랜잭션의 지금 상태로 한다(11절 끝)."""
    row = db.get(SuggestionRow, suggestion_id)
    rendered = _render(db, row)
    if rendered is not None:
        record_event(db, core.suggested_event(map_id, rendered))


def _still_there(db: Session, draft: core.Signal, map_id: str, now: datetime, th: timedelta) -> bool:
    """상태 재확인(12.8) — 저장 트랜잭션 안에서 다시 읽은 사본으로 같은 탐지기를 돌린다. 기준 시간은 관찰 때 값을
    그대로 쓴다(재확인 사이에 기준이 움직여 신호가 깜빡이지 않게)."""
    fresh = snapshot.build(db, map_id, now)
    return fresh is not None and core.recheck(draft, fresh, now, th)


# ---------------------------------------------------------------- 우리 조건 요약 (8절, 12.4 8단계)

def update_summary(
    map_id: str, snap: snapshot.Snapshot, hist: core.History, now: datetime, *,
    session_factory: SessionFactory = SessionLocal, gateway: deps.AgentLlmGateway | None = None,
) -> str | None:
    """갱신할 카테고리가 있으면 하나만 다시 만든다(core.pick_summary — 새 사유 3개, 새 구성원의 첫 반응, 사라진 사유).
    남은 카테고리가 있으면 커서를 지금으로 당겨 다음 tick에 이어 간다. agent_runs에 남긴 outcome을 돌려주고, 갱신할
    것이 없거나 저장 단계에서 지도가 삭제된 것을 보면 None.

    읽기는 도구처럼 짧은 세션으로 하고(사유는 pins에서 다시 읽는다 — 삭제된 핀의 사유 포함), ②는 세션 없이 부른다(12.6).
    저장은 지도 제안과 별도 트랜잭션이다. 문구가 고정이라 모델 사용 상한을 보지 않고 used_model=false로 남긴다."""
    category, more = core.pick_summary(snap, hist.summaries)
    if category is None:
        return None
    started = time.monotonic()
    gateway = gateway or deps.get_llm_gateway()
    ctx = tools.ToolContext(map_id=map_id, snap=snap, allowed=(), session_factory=session_factory,
                            structure=gateway.structure, now=now)
    try:
        stored, outcome, detail = core.summarize_reasons(tools.summary_reasons(ctx, category)), "summarized", None
    except llm_api.PlanEvidenceFailed as exc:
        log.warning("agent 요약 실패(②) map_id=%s category=%s", map_id, category)
        stored, outcome, detail = None, "model_failed", {"reason": "structure_failed", "detail": type(exc).__name__}

    with _write(session_factory) as db:
        if not maps_api.lock_map_if_alive(db, map_id):   # 그새 지도가 삭제됐다. 아무것도 쓰지 않는다
            return None
        run_id = service.insert_run(
            db, map_id=map_id, started_at=now, finished_at=now + timedelta(seconds=time.monotonic() - started),
            trigger="summary", snapshot_at=now, snapshot_seq=snap.latest_seq, used_model=False, outcome=outcome,
            outcome_detail={"category": category} | (detail or {}),
        )
        if stored is not None:
            service.upsert_summary(db, map_id=map_id, category=category, summary=stored, run_id=run_id, now=now)
            rendered = core.render_summary(category, stored, now, recommend_api.fact_labels())
            record_event(db, core.summary_updated_event(map_id, rendered))
            if more:
                service.wake_cursor(db, map_id, now)
    return outcome


def _summaries(db: Session, map_id: str) -> list[AgentSummary]:
    """저장된 요약을 렌더한다(카테고리는 categories.pinnable() 순서). 키 이름은 지금의 recommend 표시 이름이다."""
    rows = service.list_summaries(db, map_id)
    if not rows:
        return []
    labels = recommend_api.fact_labels()
    order = {c: i for i, c in enumerate(categories.all_categories())}
    return [core.render_summary(r.category, r.summary, r.updated_at, labels)
            for r in sorted(rows, key=lambda r: order.get(r.category, len(order)))]


# ---------------------------------------------------------------- 렌더 (11절 끝)

def _render(db: Session, row: SuggestionRow) -> AgentSuggestion | None:
    """저장된 슬롯 문장을 지금 상태로 렌더한다. 핀 이름과 사유 글은 여기서만 읽는다(명세 2절 13번). split 분석의 축
    이름은 recommend의 키 표시 이름이다(#564)."""
    pin_ids = set(core.referenced_pin_ids(row.claims))
    refs = core.RenderRefs(
        pin_names=_pin_names(db, row.map_id, pin_ids) if pin_ids else {},
        reaction_texts=_reaction_texts(db, row.map_id, row.category) if core.quoted_reaction_ids(row.claims) else {},
        fact_labels=recommend_api.fact_labels() if row.analysis else {},
    )
    return core.render_suggestion(row, refs)


def _pin_names(db: Session, map_id: str, pin_ids: set[str]) -> dict[str, str]:
    """삭제되지 않은 공개 핀의 이름 — db 핀은 장소 이름(places), 실시간 핀은 사용자가 친 검색어(#382). 지워졌거나
    이름을 찾지 못한 핀은 빠진다(그 핀을 가리키는 문장은 렌더에서 빠진다)."""
    pins = [p for p in pins_api.list_reaction_matrix(db, map_id=map_id) if p["pin_id"] in pin_ids]
    places = places_api.get_places([p["place_id"] for p in pins if p["source"] != "live" and p["place_id"]], db=db)
    names = {}
    for p in pins:
        info = places.get(p["place_id"]) if p["source"] != "live" else None
        name = p["search_query"] if p["source"] == "live" else (info.name if info else None)
        if name:
            names[p["pin_id"]] = name
    return names


def _reaction_texts(db: Session, map_id: str, category: str | None) -> dict[str, str]:
    """지금 있는 반응의 사유 글(quote 렌더용). 코드 유형은 quote가 없어 M1-2(#533) 진단부터 쓴다."""
    texts = {}
    for c in [category] if category else categories.pinnable():
        for r in pins_api.list_reasoned_reactions(db, map_id=map_id, category=c):
            if r["reason_text"]:
                texts[r["reaction_id"]] = r["reason_text"]
    return texts


# ---------------------------------------------------------------- 화면 요청 (14절)

def get_state(db: Session, *, map_id: str, user_id: str, now: datetime) -> AgentState:
    """GET /maps/{mapId}/agent. 지금 제안은 shadow가 아니고 만료 전인 활성 제안을 렌더한 것. 모드가 꺼져 있으면 null.
    요약은 만들어진 카테고리만(8절)."""
    settings = core.settings_view(service.get_settings(db, map_id))
    row = service.active_suggestion(db, map_id, now) if settings.enabled else None
    active = _render(db, row) if row is not None else None
    viewed = active is not None and service.has_viewed(db, row.id, user_id)
    return core.agent_state(settings, active, viewed=viewed, summaries=_summaries(db, map_id))


def change_settings(db: Session, *, map_id: str, enabled: bool, user_id: str, now: datetime) -> AgentSettings:
    """PUT /maps/{mapId}/agent/settings. 끄면 활성 제안을 superseded로(agent.resolved), 켜면 다음 tick에 관찰하도록
    커서를 당긴다(12.9). 둘 다 agent.settings_changed. 지금과 같은 값이면 쓰지도 알리지도 않는다.

    지도 행을 먼저 잠가 관찰의 저장 트랜잭션(observe_map 7단계도 지도 행을 잠근다)과 줄을 세운다 — 관찰이 끝난 뒤
    끄면 방금 넣은 제안도 superseded가 되고, 끈 뒤에 관찰이 저장하러 오면 모드를 보고 넣지 않는다."""
    if not maps_api.lock_map_if_alive(db, map_id):
        raise AppError("NOT_FOUND")
    current = core.settings_view(service.get_settings(db, map_id))
    if current.enabled == enabled:
        return current
    service.save_settings(db, map_id=map_id, enabled=enabled, user_id=user_id, now=now)
    if enabled:
        service.wake_cursor(db, map_id, now)
    else:
        _announce_resolved(db, map_id, service.supersede_active(db, map_id, now), "superseded")
    record_event(db, core.settings_changed_event(map_id, enabled, user_id))
    return AgentSettings(enabled=enabled, updated_by=user_id, updated_at=now)


def view(db: Session, *, row: SuggestionRow, user_id: str, now: datetime) -> None:
    """POST /agent/suggestions/{id}/view. 사람마다 한 번(멱등). 이미 처리된 제안도 기록한다. 이벤트 없음."""
    service.record_view(db, row.id, user_id, now)


def accept(db: Session, *, row: SuggestionRow, action_index: int, user_id: str, now: datetime) -> AgentAcceptResponse:
    """POST /agent/suggestions/{id}/accept. 버튼 범위 밖이면 422, 이미 처리됐거나 만료 시각이 지났으면 409.
    서버는 그 버튼의 동작을 실행하지 않고 설명(AgentAction)만 돌려준다(16.3)."""
    action = core.action_at(row.actions, action_index)
    if action is None:
        raise AppError("VALIDATION_ERROR", detail={"action_index": action_index, "actions": len(row.actions)})
    resolved = service.resolve_suggestion(
        db, row.id, status="accepted", user_id=user_id, now=now, action={"index": action.index, "type": action.type},
    )
    if not resolved:
        raise AppError("SUGGESTION_RESOLVED")
    record_event(db, core.resolved_event(row.map_id, str(row.id), "accepted", action.type))
    return AgentAcceptResponse(action=action)


def dismiss(db: Session, *, row: SuggestionRow, user_id: str, now: datetime) -> None:
    """POST /agent/suggestions/{id}/dismiss. 지도 단위로 모두에게서 닫힌다. 이미 처리됐으면 409."""
    if not service.resolve_suggestion(db, row.id, status="dismissed", user_id=user_id, now=now):
        raise AppError("SUGGESTION_RESOLVED")
    record_event(db, core.resolved_event(row.map_id, str(row.id), "dismissed"))


def _next_check(
    snap: snapshot.Snapshot, hist: core.History, now: datetime, th: timedelta, new_expires_at: datetime | None,
) -> datetime | None:
    """시간 기준이 가장 먼저 만료될 시각(12.4). 방금 넣은 제안의 만료도 후보다. 가장 최근 이벤트가 2초 안이면 지금으로
    당겨 다음 tick에 한 번 더 본다 — 그보다 작은 seq가 늦게 커밋됐어도 그 관찰에 들어간다(12.5)."""
    candidates = [t for t in (core.next_check_at(snap, hist, now, th), new_expires_at) if t is not None]
    if core.has_recent_event(snap.latest_event_at, now):
        candidates.append(now)
    return min(candidates) if candidates else None


# ---------------------------------------------------------------- 추천 막힘 조언 (9절, #587)

def advise_run(
    run_id: str, requester_id: str, *, now: datetime | None = None, session_factory: SessionFactory = SessionLocal,
    gateway: deps.AgentLlmGateway | None = None,
) -> RunAdvice | None:
    """GET /runs/{runId}/advice(agent/router.py)가 부른다. 그 run의 요청자에게 그 run의 데이터로만 조언한다(2절 2번 예외).

    1. 짧은 읽기: run(없으면 NOT_FOUND, 요청자가 아니면 FORBIDDEN), 저장된 조언(있으면 그대로 렌더해 돌려준다), 대상 판정
       재료(같은 카테고리 run), 검증 재료(근거 줄, 구성원 표시 이름 — 모델에는 가지 않는다).
    2. 대상이 아니면 None(204). 아무것도 쓰지 않는다 — 진행 중인 run은 끝난 뒤 다시 부르면 된다.
    3. 모델(세션 없음, 12.6): 깔때기를 미리 읽어(t0) 입력에 넣고 Gateway를 부른다. 도구는 자기 세션을 짧게 연다.
    4. 짧은 쓰기: agent_runs(trigger=run_advice) 한 행과 조언 한 행(ON CONFLICT (run_id) DO NOTHING). 같은 트랜잭션에서 저장된
       행을 다시 읽어 렌더한다 — 같은 run에 동시에 두 요청이 와도 먼저 커밋한 조언 하나만 남고 둘 다 그것을 돌려준다.
       침묵, 실패, 검증 실패도 빈 조언으로 저장해 다시 만들지 않는다.

    지도 모델 사용 상한에는 세지 않는다(9절 — service.MODEL_RUN_TRIGGERS에 run_advice가 없다). outcome은 advised(조언을
    만듦), silent, unknown, invalid_schema, model_failed, invalid_claims다."""
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)

    with _short_read(session_factory) as db:
        meta = recommend_api.get_run_meta(db, run_id=run_id)
        if meta["requested_by"] != requester_id:
            raise AppError("FORBIDDEN")
        stored = service.get_run_advice(db, run_id)
        if stored is not None:
            return core.render_run_advice(run_id, stored)
        recent = recommend_api.get_recent_runs(db, run_id=run_id)
        evidence = recommend_api.get_run_evidence(db, run_id=run_id)
        found = maps_api.get_map_for_agent(db, meta["map_id"])
        members = [m["user_id"] for m in found["members"]] if found else []
        names = list(auth_api.display_names(db, members).values())

    same_runs = core.same_category_runs(recent, meta["created_at"])
    if not core.run_advice_target(meta["status"], meta["result_count"], same_runs):
        return None

    gateway = gateway or deps.get_llm_gateway()
    ctx = tools.RunToolContext(
        run_id=run_id, requester_id=requester_id, meta=meta, session_factory=session_factory,
        fact_labels=recommend_api.fact_labels(),
    )
    funnel = ctx.prefetch(core.PREFETCH_CALL_ID, "get_run_funnel")
    reply = gateway.advise_run(core.advice_input(meta, same_runs, funnel), tool_runner=ctx.run)
    outcome, draft, verification, detail = _checked_advice(reply.result, ctx, evidence, names, meta)

    with _write(session_factory) as db:
        agent_run_id = uuid.uuid4()
        inserted = service.insert_run_advice(
            db, run_id=run_id, map_id=meta["map_id"], draft=draft, agent_run_id=agent_run_id, now=now,
        )
        service.insert_run(
            db, id=agent_run_id, map_id=meta["map_id"], started_at=now,
            finished_at=now + timedelta(seconds=time.monotonic() - started), trigger="run_advice", used_model=True,
            tool_calls=ctx.calls, verification=verification, outcome=outcome,
            outcome_detail={"run_id": run_id, "stored": inserted, **detail}, **core.model_usage([reply.usage]),
        )
        return core.render_run_advice(run_id, service.get_run_advice(db, run_id))


def _checked_advice(
    out: Any, ctx: tools.RunToolContext, evidence: list[dict[str, Any]], names: list[str], meta: Mapping[str, Any],
) -> tuple[str, core.AdviceDraft, dict[str, Any] | None, dict[str, Any]]:
    """모델 결과 → (outcome, 저장할 조언, verification, outcome_detail). 실패(AgentCallFailed)는 재요청하지 않고 빈 조언이다."""
    if isinstance(out, AgentCallFailed):
        return core.failed_outcome(out.reason), core.EMPTY_ADVICE, None, {"reason": out.reason, "detail": out.detail}
    verified = core.verify_run_advice(out, core.AdviceContext(
        run_id=ctx.run_id, tool_results=ctx.results, tool_names=ctx.names,
        own_lines={line["line_id"]: line["author_id"] == ctx.requester_id for line in evidence},
        evidence_texts=[line["text"] for line in evidence if line["text"]],
        radius=core.radius_limits(meta["default_radius_walk_min"], meta["widen_limit_walk_min"]), member_names=names,
    ))
    return verified.outcome, verified.draft, verified.record, {"decision": out.decision, "kind": out.kind}
