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
따로 돌고(요청 안), 종류·문장·버튼은 코드가 정한다(core.choose_run_advice, #750 — 모델 없음). 읽기 → 고르기 → 쓰기를 짧은
세션으로 나누고 run당 한 번 저장한다(trigger=run_advice). 계산이 예외로 끝나면 error 행만 남기고 예외를 올린다(500 — 조언
없음 204와 가른다). 조언은 저장하지 않아 다음 요청이 다시 만든다.

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
- error: 관찰이 예외로 끝남(#677). run_tick이 따로 남기고 outcome_detail은 {stage, error(예외 클래스 이름)}뿐이다. 진단을
  부른 뒤면 used_model=true와 그때까지의 사용량, tool_calls를 함께 남긴다. 커서를 올리고 재시도를 미룬다(_observe_claimed)
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
from agent.constants import CODE_TYPES, DECIDED_WINDOW, SUGGESTION_TTL, TICK_BUDGET_SEC, TICK_MAX_MAPS
from agent.models import AgentSuggestion as SuggestionRow
from agent.schemas import (
    AgentAcceptResponse,
    AgentCallFailed,
    AgentReply,
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
from shortlist import api as shortlist_api

log =logging.getLogger("pingo.agent")

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


@dataclass
class _Trace:
    """관찰 한 번이 어디까지 갔는지(#677). 흐름이 단계마다 고치고, 예외로 끝나면 이것으로 error 행을 남긴다.

    단계: expire → snapshot → detect → draft → model → verify → save → summary.
    모델 사용(used_model, tool_calls, usage)은 아직 어느 행에도 남지 않은 것만 담는다 — 관찰의 저장 단계가 커밋되면 지도
    관찰 행에 들어갔으므로 비운다(model_recorded). tool_calls는 도구 창구의 기록(글 대신 글자 수) 그대로다."""
    stage: str
    started: float = field(default_factory=time.monotonic)
    used_model: bool = False
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: AgentUsage | None = None

    def model_recorded(self) -> None:
        self.used_model, self.tool_calls, self.usage = False, [], None

    def error_fields(self, exc: Exception, now: datetime) -> dict[str, Any]:
        """error 행의 칸. outcome_detail은 단계와 예외 클래스 이름뿐이다 — str(예외)에는 사유 글이나 SQL 값이 들어 있을 수
        있다. 모델을 이미 불렀으면 used_model=true와 그때까지의 사용량을 남겨 지도 상한에 센다(12.3)."""
        return {
            "started_at": now, "finished_at": now + timedelta(seconds=time.monotonic() - self.started),
            "used_model": self.used_model, "tool_calls": self.tool_calls, "outcome": "error",
            "outcome_detail": {"stage": self.stage, "error": type(exc).__name__},
            **core.model_usage([self.usage] if self.usage is not None else []),
        }


def _call_model(trace: _Trace, tool_calls: list[dict[str, Any]], call: Callable[[], AgentReply]) -> AgentReply:
    """모델 단계(진단). 부르기 전에 모델 사용을 표시하고, 도구가 예외를 내도(llm의 ToolRunnerError) 그때까지 쓴 사용량을
    trace에 남긴다(#677)."""
    trace.stage, trace.used_model, trace.tool_calls = "model", True, tool_calls
    try:
        reply = call()
    except llm_api.ToolRunnerError as exc:
        trace.usage = exc.usage
        raise
    trace.usage = reply.usage
    return reply


# ---------------------------------------------------------------- tick (12.2)

def run_tick(
    now: datetime, *, session_factory: SessionFactory = SessionLocal, gateway: deps.AgentLlmGateway | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> list[str]:
    """지도를 골라(lease) 하나씩 관찰한다. 한 지도가 실패해도 다른 지도는 계속하고, lease는 늘 푼다. 관찰한 map_id 목록
    (예외로 끝난 것 포함)을 돌려준다. gateway가 없으면 deps.get_llm_gateway()(LLM_MODE로 고른 것).

    시간 예산(#677): 시작 뒤 TICK_BUDGET_SEC(LEASE_SEC − 30초)가 지나면 남은 지도는 관찰하지 않고 lease만 푼다 — 관찰이
    lease 시간을 넘겨 다른 실행이 같은 지도를 잡지 않게 한다. 남은 지도는 커서가 그대로라 다음 tick에 다시 잡힌다.

    끝날 때 처리량을 숫자로만 한 줄 남긴다(#756) — 차례였던 지도 수, 관찰한 수, TICK_MAX_MAPS로 미룬 수, 시간 예산으로
    미룬 수, 걸린 ms. 지도 id와 사용자 데이터는 넣지 않는다. 예산으로 미룬 지도가 있으면 warning이다."""
    started = clock()
    gateway = gateway or deps.get_llm_gateway()
    with _write(session_factory) as db:
        claims, due = service.claim_maps(db, now, limit=TICK_MAX_MAPS)
    observed = []
    for claim in claims:
        try:
            if clock() - started < TICK_BUDGET_SEC:
                _observe_claimed(claim, now, session_factory, gateway)
                observed.append(claim.map_id)
        finally:
            try:
                with _write(session_factory) as db:
                    service.release_lease(db, claim.map_id, claim.token)
            except Exception as exc:   # 못 풀어도 LEASE_SEC 뒤에는 다른 실행이 가져간다(12.5)
                log.warning("agent release_lease 실패 map_id=%s error=%s", claim.map_id, type(exc).__name__)
    try:
        daily_cleanup_if_due(now, session_factory=session_factory)
    except Exception as exc:   # 마친 날짜를 적지 않았으니 다음 tick이 다시 한다
        log.warning("agent 보존 정리 실패 error=%s", type(exc).__name__)
    deferred_by_budget = len(claims) - len(observed)
    log.log(logging.WARNING if deferred_by_budget else logging.INFO,
            "agent tick due=%d observed=%d deferred_by_max=%d deferred_by_budget=%d elapsed_ms=%d",
            due, len(observed), max(due - len(claims), 0), deferred_by_budget, round((clock() - started) * 1000))
    return observed


def _observe_claimed(
    claim: service.Claim, now: datetime, session_factory: SessionFactory, gateway: deps.AgentLlmGateway,
) -> None:
    """관찰 하나. 예외로 끝나면 error 행을 남기고 재시도를 미룬다(#677) — 기록 없이 두면 커서가 그대로라 같은 지도가 tick마다
    다시 잡히고, 모델을 부른 뒤의 실패면 관찰마다 모델을 다시 부른다.

    커서는 고를 때 본 가장 큰 seq로 올리고, next_check_at은 그 지도에서 연달아 예외로 끝난 관찰 수(service.error_streak)에
    따라 30분, 2시간, 6시간 뒤다(core.error_retry_at). 다음 관찰은 도메인 테이블에서 다시 읽으므로 커서를 올려도 잃는 것이
    없다(12.5). 그사이 새 이벤트가 오면 activity로 다시 잡힌다."""
    trace = _Trace("expire")
    try:
        observe_map(claim.map_id, now, trigger=claim.trigger, session_factory=session_factory, gateway=gateway,
                    trace=trace, token=claim.token)
    except Exception as exc:
        log.error("agent observe_map 실패 map_id=%s stage=%s error=%s", claim.map_id, trace.stage, type(exc).__name__)
        try:
            with _write(session_factory) as db:
                if not service.lease_held(db, claim.map_id, claim.token):   # lease를 잃었다. 기록도 커서도 건드리지 않는다
                    log.warning("agent lease 잃음 map_id=%s stage=%s", claim.map_id, trace.stage)
                    return
                service.insert_run(db, map_id=claim.map_id, trigger=claim.trigger, **trace.error_fields(exc, now))
                retry_at = core.error_retry_at(now, service.error_streak(db, claim.map_id))
                service.advance_cursor(db, claim.map_id, claim.seq, next_check_at=retry_at, observed_at=now,
                                       token=claim.token)
        except Exception as record_exc:
            log.error("agent 관찰 실패 기록 실패 map_id=%s error=%s", claim.map_id, type(record_exc).__name__)


_cleanup_done_on: date | None = None   # 이 프로세스가 보존 정리를 마친 KST 날짜


def daily_cleanup_if_due(now: datetime, *, session_factory: SessionFactory = SessionLocal) -> bool:
    """하루 한 번(KST) 정리한다(12.9): agent_runs 30일 초과분을 지우고, 24시간 지난 제안의 decided_within_24h를 채운다.
    했으면 True. 날짜는 프로세스 메모리에 둔다 — 인스턴스가 여럿이거나 다시 뜨면 하루에 몇 번 돌 수 있지만 지우기와
    빈 칸 채우기라 결과는 같다."""
    global _cleanup_done_on
    today = core.kst_date(now)
    if _cleanup_done_on == today:
        return False
    with _write(session_factory) as db:
        deleted = service.delete_old_runs(db, now)
    filled = fill_decided_within_24h(now, session_factory=session_factory)
    _cleanup_done_on = today
    log.info("agent 보존 정리: agent_runs %d행 삭제, decided_within_24h %d행 채움", deleted, filled)
    return True


def fill_decided_within_24h(now: datetime, *, session_factory: SessionFactory = SessionLocal) -> int:
    """만든 지 24시간이 넘었고 decided_within_24h가 빈 제안(shadow 포함, 상태 무관)을 채운다(12.9, #613). 채운 행 수.

    지도마다 짧은 쓰기 트랜잭션 하나에서 다른 모듈을 한 번씩 읽고(지도, 확정 리스트, 카테고리 유형이 있으면 핀) 그 지도
    제안을 한 번에 쓴다. 한 지도가 실패해도 다른 지도는 계속한다(그 지도는 다음 정리 때 다시 본다)."""
    created_before = now - DECIDED_WINDOW
    with _short_read(session_factory) as db:
        map_ids = service.list_undecided_map_ids(db, created_before=created_before)
    filled = 0
    for map_id in map_ids:
        try:
            with _write(session_factory) as db:
                filled += _fill_decided_for_map(db, map_id, created_before)
        except Exception as exc:
            log.warning("agent decided_within_24h 채우기 실패 map_id=%s error=%s", map_id, type(exc).__name__)
    return filled


def _fill_decided_for_map(db: Session, map_id: str, created_before: datetime) -> int:
    found = maps_api.get_map_for_agent(db, map_id)
    if found is None or found["deleted"]:   # 판정하지 않고 둔다. 삭제 30일 뒤 지도 정리가 지운다
        return 0
    targets = service.list_undecided(db, map_id=map_id, created_before=created_before)
    if not targets:
        return 0
    category_of: dict[str, str] = {}
    if any(t.diagnosis in core.CATEGORY_DECIDED for t in targets):
        # 공개된 살아 있는 핀만 분류가 나온다. 삭제된 핀은 세지 않는다(agent-v2 12.9, #613)
        category_of = {p["pin_id"]: p["category"] for p in pins_api.list_reaction_matrix(db, map_id=map_id)}
    confirmations = [
        core.Confirmation(pin_id=i["pin_id"], category=category_of.get(i["pin_id"]), added_at=i["added_at"])
        for i in shortlist_api.list_items_for_agent(db, map_id=map_id)
    ]
    return service.set_decided(db, {t.id: core.decided_within_24h(t, confirmations) for t in targets})


# ---------------------------------------------------------------- 관찰 (12.4)

def observe_map(
    map_id: str, now: datetime, *, trigger: str = "activity", session_factory: SessionFactory = SessionLocal,
    gateway: deps.AgentLlmGateway | None = None, trace: _Trace | None = None, token: str | None = None,
) -> str | None:
    """지도 하나를 관찰하고 agent_runs에 남긴 outcome을 돌려준다. 저장 단계에서 지도가 삭제된 것을 보면 아무것도
    쓰지 않고 None(머리말의 outcome 목록). token은 run_tick이 잡은 lease의 주인 표시다(#812) — 저장할 때 그 lease가 아직
    내 것이 아니면(오래 걸린 사이 다른 실행이 다시 잡았다) 결과를 저장하지 않고 stale 행만 남긴다. 직접 부르면(token 없음) 확인하지
    않는다. 예외는 그대로 올린다 — 어디까지 갔는지는 trace에 남는다(run_tick이 error 행을
    쓴다, #677)."""
    started = time.monotonic()
    gateway = gateway or deps.get_llm_gateway()
    trace = trace if trace is not None else _Trace("expire")

    def run_fields(snap: snapshot.Snapshot | None, outcome: str, **extra: Any) -> dict[str, Any]:
        return {
            "map_id": map_id, "started_at": now, "finished_at": now + timedelta(seconds=time.monotonic() - started),
            "trigger": trigger, "snapshot_at": now, "snapshot_seq": snap.latest_seq if snap else None,
            "used_model": False, "outcome": outcome, **extra,
        }

    def lease_lost(db: Session, snap: snapshot.Snapshot | None) -> str:
        db.flush()
        service.insert_run(db, **run_fields(snap, "stale", outcome_detail={"reason": "lease_lost"}))
        log.warning("agent lease 잃음 map_id=%s", map_id)
        return "stale"

    # 1. 만료 정리 (짧은 쓰기) + agent.resolved
    trace.stage = "expire"
    with _write(session_factory) as db:
        _announce_resolved(db, map_id, service.expire_suggestions(db, map_id, now), "expired")

    # 2. 스냅샷과 이력 (짧은 읽기, REPEATABLE READ). 여기서 세션을 닫는다
    trace.stage = "snapshot"
    with _snapshot_read(session_factory) as db:
        snap = snapshot.build(db, map_id, now)
        hist = service.load_history(db, map_id, now)
        # 검증(11.2 5단계)이 문장에서 찾는 표시 이름. 모델에는 가지 않는다
        names = list(auth_api.display_names(db, [m.user_id for m in snap.members]).values()) if snap else []

    ended = _ended(snap)
    if ended is not None:   # 끝난 지도는 관찰하지 않는다. 새 이벤트가 와야 다시 잡히고, 그때도 바로 끝난다
        trace.stage = "save"
        with _write(session_factory) as db:
            if token is not None and not service.lease_held(db, map_id, token):
                return lease_lost(db, snap)
            service.insert_run(db, **run_fields(snap, ended))
            service.advance_cursor(db, map_id, snap.latest_seq if snap else None, next_check_at=None, observed_at=now,
                                   token=token)
        return ended

    # 3. 탐지와 활성 제안 무효화 판단 (순수)
    trace.stage = "detect"
    th = core.time_threshold(snap.action_times, snap.map.start_date, snap.today)
    signals = core.detect_all(snap, now, th)
    superseding = core.find_superseded(hist.active, signals)

    # 4. 정책 사전 검사 (순수)
    passed, blocked = core.check_policy(signals, hist, snap, now, superseding=superseding)

    # 5. 우선순위 — 코드 규칙(7절, #582). 모델을 부르지 않는다
    policy = core.load_policy()
    top, priority = core.choose_top(passed, policy)

    # 6. 초안 — 코드 유형은 템플릿, 모델 유형은 진단과 검증(세션 없음, 도구만 짧게 읽는다)
    trace.stage = "draft"
    step = _draft(map_id, top, snap, names, now, session_factory, gateway, trace) if top is not None else _Step(None)
    chosen = top if step.draft is not None else None
    draft = step.draft
    outcome, detail = _planned_outcome(signals, top, step)
    usages = [step.usage] if step.usage is not None else []

    # 7. 재확인과 저장 (짧은 쓰기 트랜잭션). 이벤트도 같은 트랜잭션
    trace.stage = "save"
    with _write(session_factory) as db:
        if token is not None and not service.lease_held(db, map_id, token):   # 커서 행을 잠근 뒤 지도 행을 잠근다
            return lease_lost(db, snap)
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
            observed_at=now, token=token,
        )
    trace.model_recorded()   # 진단의 모델 사용은 위 행에 남았다. 요약에서 실패해도 다시 세지 않는다

    # 8. 요약 (별도 흐름, 별도 트랜잭션)
    trace.stage = "summary"
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
    session_factory: SessionFactory, gateway: deps.AgentLlmGateway, trace: _Trace,
) -> _Step:
    """제안 초안(12.4 6단계). 코드 유형은 템플릿. 모델 유형은 진단을 부른다 — split은 충돌 종류(compare_reasons, 코드)를
    먼저 계산해 입력에 넣는다. 실패(AgentCallFailed)와 검증 실패는 재요청하지 않고 침묵한다(2절 10번). 예외는 그대로
    올리고, 진단을 부른 뒤면 trace에 모델 사용이 남는다(#677)."""
    if top.diagnosis in CODE_TYPES:
        return _Step(core.render_template(top))
    ctx = tools.ToolContext(
        map_id=map_id, snap=snap, allowed=llm_api.DIAGNOSIS_TOOLS[top.diagnosis], session_factory=session_factory,
        structure=gateway.structure, now=now,
    )
    # 사용량 기록(#870): 진단 왕복과 그 안의 ②(사전 비교, 도구)가 한 trace다. 서버 호출이라 user_id가 없고, agent_runs 행은
    # 아직 없어 run_id도 없다
    with llm_api.usage_context("agent_diagnose", map_id=map_id):
        comparison = _comparison(ctx, top)
        reply = _call_model(trace, ctx.calls, lambda: gateway.diagnose(
            core.diagnosis_input(top, snap, comparison), tool_runner=ctx.run,
        ))
    trace.stage = "verify"
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
        with llm_api.usage_context("agent_summary", map_id=map_id):   # #870 — ②를 부르지만 지도 상한에는 세지 않는다
            reasons = tools.summary_reasons(ctx, category)
        stored, outcome, detail = core.summarize_reasons(reasons), "summarized", None
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


# ---------------------------------------------------------------- 추천 막힘 조언 (9절, #587, #750)

def advise_run(
    run_id: str, requester_id: str, *, now: datetime | None = None, session_factory: SessionFactory = SessionLocal,
) -> RunAdvice | None:
    """GET /runs/{runId}/advice(agent/router.py)가 부른다. 그 run의 요청자에게 그 run의 데이터로만 조언한다(2절 2번 예외).
    종류, 문장, 버튼은 코드가 정한다(core.choose_run_advice, #749 결정 — 모델 없음).

    1. 짧은 읽기: run(없으면 NOT_FOUND, 요청자가 아니면 FORBIDDEN), 저장된 조언(있으면 그대로 렌더해 돌려준다), 대상 판정
       재료(같은 카테고리 run). 대상이 아니면 None(204) — 아무것도 쓰지 않는다. 진행 중인 run은 끝난 뒤 다시 부르면 된다.
    2. 짧은 읽기: 깔때기, 근거 줄, 필요한 시뮬레이션(core.advice_simulations — 앞 결과를 기다리지 않는다). 그리고 고르기(순수,
       core.choose_run_advice).
    3. 짧은 쓰기: agent_runs(trigger=run_advice) 한 행과 조언 한 행(ON CONFLICT (run_id) DO NOTHING). 같은 트랜잭션에서 저장된
       행을 다시 읽어 렌더한다 — 같은 run에 동시에 두 요청이 와도 먼저 커밋한 조언 하나만 남고 둘 다 그것을 돌려준다.
       침묵도 빈 조언으로 저장해 다시 만들지 않는다.

    2단계가 예외로 끝나면 agent_runs에 outcome=error 한 행(run, 예외 클래스 이름)만 남기고 예외를 올린다(라우터에서 500) —
    "조언 없음"(204)과 "실패"를 같은 응답으로 두지 않는다. 조언 행은 저장하지 않으므로 다음 요청이 다시 만든다.

    지도 모델 사용 상한에는 세지 않는다(service.MODEL_RUN_TRIGGERS에 run_advice가 없다). outcome은 advised(조언을 만듦), silent, error다. tool_calls에는 읽은 것(깔때기 t0, 근거 줄 t1, 시뮬레이션 t2 …)을
    남긴다 — claim의 call_id가 가리키는 기록이다. 근거 글은 읽기 결과에 없다."""
    started = time.monotonic()
    now = now or datetime.now(timezone.utc)

    with _short_read(session_factory) as db:
        meta = recommend_api.get_run_meta(db, run_id=run_id)
        if meta["requested_by"] != requester_id:
            raise AppError("FORBIDDEN")
        stored = service.get_run_advice(db, run_id)
        if stored is not None:
            return core.render_run_advice(run_id, stored)
        same_runs = core.same_category_runs(recommend_api.get_recent_runs(db, run_id=run_id), meta["created_at"])
        if not core.run_advice_target(meta["status"], meta["result_count"], same_runs):
            return None

    reads = _AdviceReads()
    try:
        with _short_read(session_factory) as db:
            funnel = reads.add(core.FUNNEL_CALL_ID, "get_run_funnel", {},
                               lambda: core.funnel_view(recommend_api.get_run_funnel(db, run_id=run_id)))
            lines = reads.add(core.EVIDENCE_CALL_ID, "get_run_evidence", {}, lambda: core.advice_evidence(
                recommend_api.get_run_evidence(db, run_id=run_id), requester_id, recommend_api.fact_labels()))
            next_factor = core.next_radius_factor(meta)
            sims = {
                call_id: reads.add(call_id, "simulate_filter", args, lambda args=args: core.simulate_view(
                    recommend_api.simulate_filter(db, run_id=run_id, **args), **args))
                for call_id, args in core.advice_simulations(funnel, lines, next_factor).items()
            }
        draft = core.choose_run_advice(run_id, funnel, lines, sims, next_factor)
    except Exception as exc:
        log.error("agent 조언 실패 run_id=%s error=%s", run_id, type(exc).__name__)
        with _write(session_factory) as db:   # 조언 행은 쓰지 않는다 — 다음 요청이 다시 만든다
            service.insert_run(
                db, map_id=meta["map_id"], started_at=now, trigger="run_advice", used_model=False,
                finished_at=now + timedelta(seconds=time.monotonic() - started), tool_calls=reads.calls, outcome="error",
                outcome_detail={"run_id": run_id, "error": type(exc).__name__},   # 예외 메시지는 남기지 않는다(#677)
            )
        raise

    with _write(session_factory) as db:
        agent_run_id = uuid.uuid4()
        inserted = service.insert_run_advice(
            db, run_id=run_id, map_id=meta["map_id"], draft=draft, agent_run_id=agent_run_id, now=now,
        )
        service.insert_run(
            db, id=agent_run_id, map_id=meta["map_id"], started_at=now,
            finished_at=now + timedelta(seconds=time.monotonic() - started), trigger="run_advice", used_model=False,
            tool_calls=reads.calls, outcome="silent" if draft.kind is None else "advised",
            outcome_detail={"run_id": run_id, "stored": inserted, "decision": draft.decision, "kind": draft.kind},
        )
        return core.render_run_advice(run_id, service.get_run_advice(db, run_id))


@dataclass
class _AdviceReads:
    """조언 한 번이 읽은 것의 기록(agent_runs.tool_calls) — 진단 도구 기록(tools._record)과 같은 모양 {call_id, name, args,
    result, ms}. 결과에 근거 글이 없어 그대로 남긴다."""
    calls: list[dict[str, Any]] = field(default_factory=list)

    def add(self, call_id: str, name: str, args: Mapping[str, Any], read: Callable[[], Any]) -> Any:
        started = time.monotonic()
        result = read()
        self.calls.append({"call_id": call_id, "name": name, "args": dict(args), "result": result,
                           "ms": int((time.monotonic() - started) * 1000)})
        return result
