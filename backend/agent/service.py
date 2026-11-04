"""agent_* 테이블 읽기와 쓰기. 커밋하지 않는다(커밋은 호출부의 session_scope 한 곳).

- 정리: 지도 정리(`purge_map_data`), 탈퇴(`delete_by_user`) — #513
- 관찰 흐름(#515, 명세 12.2~12.5, 12.9): 지도 고르기와 lease(`claim_maps`, `release_lease`), 커서(`advance_cursor`),
  이력(`load_history`), 제안 상태(`expire_suggestions`, `supersede`, `insert_suggestion`), 기록(`insert_run`),
  보존 정리(`delete_old_runs`), 제안 뒤 24시간 안 확정(`list_undecided_map_ids`, `list_undecided`, `set_decided` — #613),
  관찰 실패의 재시도 간격(`error_streak` — #677)
- 화면 요청(#531, 명세 14절): 모드(`get_settings`, `save_settings`, `wake_cursor`), 지금 제안(`get_suggestion`,
  `active_suggestion`), 열람(`has_viewed`, `record_view`), 수락과 닫기(`resolve_suggestion` — status='active'일 때만
  바꾸는 가드 UPDATE), 모드 끄기(`supersede_active`)
- 우리 조건 요약(#586, 명세 8절, 13절): 덮어쓰기(`upsert_summary`), 읽기(`list_summaries`). 갱신 판단이 보는 요약
  메타는 `load_history`가 함께 읽는다
- 추천 막힘 조언(#587, 명세 9절, 13절): run당 1행에 지금 결과 상태의 조언(`insert_run_advice` — ON CONFLICT (run_id) DO UPDATE ... WHERE state_key IS DISTINCT, #1103), 읽기(`get_run_advice`)
- 지도 현황 문단(#1168, 명세 8.2, 13절): 덮어쓰기(`upsert_map_status`), 읽기(`get_map_status`). 다시 만들지 판단하는 칸의
  해시는 `load_history`가 함께 읽는다
- 작업 기록과 살펴본 상태(#1297, 명세 11.3, 21.3): 제안의 관찰 행(`get_run`), 마지막 관찰 시각(`last_observed_at`),
  가장 최근 지도 관찰 행(`latest_observation`)

제안 상태를 바꾸는 함수는 (id, shadow) 목록을 돌려준다. agent.resolved는 shadow가 아닌 것만 낸다(호출부).

다른 모듈 테이블은 읽지도 쓰지도 않는다. event_log는 `realtime.api.latest_seq_by_map`으로만 본다(12.2).
"""

import uuid
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import delete, func, null, or_, select, text, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from agent import core
from agent.constants import (
    AGENT_RUNS_RETENTION_DAYS, ERROR_RETRY_DELAYS, LEASE_SEC, SUGGESTION_TTL, SUMMARY_FAILED_RETRY,
)
from agent.models import (
    AgentCursor,
    AgentMapStatus,
    AgentReasonSummary,
    AgentRun,
    AgentRunAdvice,
    AgentSettings,
    AgentSuggestion,
    AgentSuggestionView,
)
from common.kst import kst_day_start
from realtime import api as realtime_api

# 모델 사용 상한이 세는 trigger(12.3). 현황 문단(status, 8.2)은 모델을 부르지만 세지 않는다 — 비용은 서비스 일일 예산이 본다(19절)
MODEL_RUN_TRIGGERS = ("activity", "time", "summary")

PURGE_TABLES = (
    "agent_suggestion_views", "agent_suggestions", "agent_run_advice", "agent_reason_summaries", "agent_map_status",
    "agent_runs", "agent_cursors", "agent_settings",
)


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(#431) — 이 지도들의 agent_* 행을 모두 지운다. 테이블 이름 → 지운 행 수.
    열람은 제안을, 제안은 run을 참조해서 열람 → 제안 → … → run 순서로 지운다(CASCADE·SET NULL에 기대지 않고
    행 수를 세려고 직접 지운다)."""
    if not map_ids:
        return dict.fromkeys(PURGE_TABLES, 0)
    suggestion_ids = select(AgentSuggestion.id).where(AgentSuggestion.map_id.in_(map_ids))
    return {
        "agent_suggestion_views": db.execute(
            delete(AgentSuggestionView).where(AgentSuggestionView.suggestion_id.in_(suggestion_ids))
        ).rowcount,
        "agent_suggestions": db.execute(delete(AgentSuggestion).where(AgentSuggestion.map_id.in_(map_ids))).rowcount,
        "agent_run_advice": db.execute(delete(AgentRunAdvice).where(AgentRunAdvice.map_id.in_(map_ids))).rowcount,
        "agent_reason_summaries": db.execute(
            delete(AgentReasonSummary).where(AgentReasonSummary.map_id.in_(map_ids))
        ).rowcount,
        "agent_map_status": db.execute(delete(AgentMapStatus).where(AgentMapStatus.map_id.in_(map_ids))).rowcount,
        "agent_runs": db.execute(delete(AgentRun).where(AgentRun.map_id.in_(map_ids))).rowcount,
        "agent_cursors": db.execute(delete(AgentCursor).where(AgentCursor.map_id.in_(map_ids))).rowcount,
        "agent_settings": db.execute(delete(AgentSettings).where(AgentSettings.map_id.in_(map_ids))).rowcount,
    }


def delete_by_user(db: Session, *, user_id: str, map_ids: list[str]) -> dict[str, int]:
    """탈퇴(#155) — 사유 원문이 남을 수 있는 곳을 지도 단위로 비우고, 그 사람의 열람 기록을 지운다.

    - agent_suggestion_views: 그 사람의 행 전부(지도와 무관).
    - agent_reason_summaries: `map_ids` 지도의 요약 전부. 다음 관찰에서 다시 만든다(명세 12.9).
    - agent_runs: `map_ids` 지도의 run에서 tool_calls를 '[]'로, verification을 NULL로 비운다. 행은 남긴다
      (관찰 지표와 30일 보존은 그대로). 돌려주는 수는 비운 행 수다.

    agent는 반응이 누구 것인지 모르고(tool_calls에는 구성원 별칭만 있다), 반응은 같은 트랜잭션에서 곧 지워진다.
    그래서 그 사람 항목만 골라내지 않고 그 사람이 있던 지도의 것을 통째로 비운다."""
    counts = {
        "agent_suggestion_views": db.execute(
            delete(AgentSuggestionView).where(AgentSuggestionView.user_id == user_id)
        ).rowcount,
        "agent_reason_summaries": 0,
        "agent_runs": 0,
    }
    if not map_ids:
        return counts
    counts["agent_reason_summaries"] = db.execute(
        delete(AgentReasonSummary).where(AgentReasonSummary.map_id.in_(map_ids))
    ).rowcount
    counts["agent_runs"] = db.execute(
        update(AgentRun)
        .where(
            AgentRun.map_id.in_(map_ids),
            (func.jsonb_array_length(AgentRun.tool_calls) > 0) | AgentRun.verification.is_not(None),
        )
        .values(tool_calls=[], verification=null())
    ).rowcount
    return counts


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(#694) — from_user의 열람 기록, 모드를 바꾼 사람, 제안을 처리한 사람을 to_user로 옮긴다. 커밋은 호출자.
    같은 제안을 둘 다 열람했으면 from_user의 열람만 지운다(to_user 쪽 viewed_at이 이긴다). 사유 원문은 다루지 않는다
    (agent 테이블에는 원문이 없고 reaction_id만 있다). 멱등 — 옮길 게 없으면 0이고, 같은 id면 아무것도 안 한다."""
    if from_user_id == to_user_id:
        return {"agent_suggestion_views": 0, "agent_suggestion_views_dropped": 0, "agent_settings": 0,
                "agent_suggestions": 0}
    already_viewed = select(AgentSuggestionView.suggestion_id).where(AgentSuggestionView.user_id == to_user_id)
    dropped = db.execute(
        delete(AgentSuggestionView).where(
            AgentSuggestionView.user_id == from_user_id, AgentSuggestionView.suggestion_id.in_(already_viewed)
        )
    ).rowcount
    views = db.execute(
        update(AgentSuggestionView).where(AgentSuggestionView.user_id == from_user_id).values(user_id=to_user_id)
    ).rowcount
    settings = db.execute(
        update(AgentSettings).where(AgentSettings.updated_by == from_user_id).values(updated_by=to_user_id)
    ).rowcount
    suggestions = db.execute(
        update(AgentSuggestion).where(AgentSuggestion.resolved_by == from_user_id).values(resolved_by=to_user_id)
    ).rowcount
    return {"agent_suggestion_views": views, "agent_suggestion_views_dropped": dropped, "agent_settings": settings,
            "agent_suggestions": suggestions}


# ---------------------------------------------------------------- 지도 고르기와 lease (12.2, 12.5)

class Claim(NamedTuple):
    map_id: str
    trigger: str        # activity(새 이벤트) | time(시간 점검)
    token: str          # lease 주인 표시(#812). 해제, 커서 전진, 결과 저장은 이 값이 아직 같을 때만 한다
    seq: int | None     # 고를 때 본 그 지도의 가장 큰 event_log seq. 보존 24시간 안에 이벤트가 없으면 None


class Claimed(NamedTuple):
    claims: list[Claim]
    due: int            # limit 전에 관찰할 차례였던 지도 수(#756). 같은 순간 다른 실행이 잠근 지도도 셀 수 있다


def claim_maps(db: Session, now: datetime, *, limit: int) -> Claimed:
    """관찰할 지도를 골라 lease를 잡는다. 새 이벤트로 잡혔으면 trigger=activity, 시간 점검으로 잡혔으면 time. seq는
    관찰이 예외로 끝났을 때 커서를 올릴 값이다(#677). 호출부가 바로 커밋해야 lease가 다른 실행에 보인다.

    1. `realtime.api.latest_seq_by_map`으로 지도별 가장 큰 seq를 받는다. 커서 행이 없는 지도는 여기서 만든다
       (ON CONFLICT DO NOTHING — 동시에 두 실행이 만들어도 하나). 커서보다 큰 seq가 있으면 바뀐 지도다.
    2. agent_cursors만 FOR UPDATE SKIP LOCKED로 잠그고 lease_until을 올린다. maps와 event_log는 조인하지 않는다.
       모드가 꺼진 지도(agent_settings.enabled=false)는 고르지 않는다. 행이 없으면 켜짐이다.
    3. 같은 조건의 지도 수를 limit 없이 센다(#756, tick 처리량 로그). FOR UPDATE와 집계는 한 쿼리에 못 넣어 따로 센다."""
    latest = realtime_api.latest_seq_by_map(db)
    seen: dict[str, int] = dict(
        db.execute(select(AgentCursor.map_id, AgentCursor.last_seen_seq).where(AgentCursor.map_id.in_(latest))).all()
    ) if latest else {}
    missing = sorted(set(latest) - set(seen))   # 정렬해서 넣는다 — 두 실행이 같은 순서로 기다려 교착이 없다
    if missing:
        db.execute(
            pg_insert(AgentCursor).values([{"map_id": m} for m in missing]).on_conflict_do_nothing(
                index_elements=[AgentCursor.map_id]
            )
        )
    changed = {m for m, (seq, _) in latest.items() if seq > seen.get(m, 0)}

    due = (
        select(AgentCursor.map_id)
        .outerjoin(AgentSettings, AgentSettings.map_id == AgentCursor.map_id)
        .where(
            func.coalesce(AgentSettings.enabled, true()),
            or_(AgentCursor.lease_until.is_(None), AgentCursor.lease_until < now),
            or_(AgentCursor.map_id.in_(changed), AgentCursor.next_check_at <= now),
        )
    )
    due_count = db.scalar(select(func.count()).select_from(due.subquery()))
    map_ids = db.execute(
        due.order_by(AgentCursor.next_check_at.asc().nulls_last(), AgentCursor.map_id)
        .limit(limit)
        .with_for_update(of=AgentCursor, skip_locked=True)
    ).scalars().all()
    tokens = {m: uuid.uuid4() for m in map_ids}
    for m, token in tokens.items():
        db.execute(
            update(AgentCursor).where(AgentCursor.map_id == m)
            .values(lease_until=now + timedelta(seconds=LEASE_SEC), lease_token=token)
        )
    claims = [
        Claim(m, "activity" if m in changed else "time", str(tokens[m]), latest[m][0] if m in latest else None)
        for m in map_ids
    ]
    return Claimed(claims, due_count)


def lease_held(db: Session, map_id: str, token: str) -> bool:
    """이 token이 아직 그 지도 lease의 주인인가. 커서 행을 잠가 확인하므로 이 트랜잭션이 끝날 때까지 다른 실행이
    lease를 바꾸지 못한다(fencing, #812). 호출부는 결과를 저장하기 전에 부른다."""
    return db.execute(
        select(AgentCursor.map_id).where(AgentCursor.map_id == map_id, AgentCursor.lease_token == uuid.UUID(token))
        .with_for_update()
    ).first() is not None


def release_lease(db: Session, map_id: str, token: str) -> None:
    """lease를 푼다. 그새 다른 실행이 다시 잡았으면(token이 다르면) 건드리지 않는다."""
    db.execute(
        update(AgentCursor).where(AgentCursor.map_id == map_id, AgentCursor.lease_token == uuid.UUID(token))
        .values(lease_until=None, lease_token=None)
    )


def advance_cursor(
    db: Session, map_id: str, seq: int | None, *, next_check_at: datetime | None, observed_at: datetime,
    token: str | None = None,
) -> None:
    """커서 = 본 것 중 가장 큰 seq(#525). 뒤로 가지 않는다 — seq가 없거나(보존 24시간 안에 이벤트 없음) 더 작으면
    그대로 둔다. 구멍은 추적하지 않는다. 행이 없으면(지도 정리가 먼저 지움) 아무것도 하지 않는다. token이 있으면 그 lease가
    아직 같을 때만 올린다(#812)."""
    last_seen = AgentCursor.last_seen_seq if seq is None else func.greatest(AgentCursor.last_seen_seq, seq)
    where = [AgentCursor.map_id == map_id]
    if token is not None:
        where.append(AgentCursor.lease_token == uuid.UUID(token))
    db.execute(
        update(AgentCursor).where(*where)
        .values(last_seen_seq=last_seen, next_check_at=next_check_at, last_observed_at=observed_at)
    )


# ---------------------------------------------------------------- 이력 (12.3)

def load_history(db: Session, map_id: str, now: datetime) -> core.History:
    """정책이 보는 이 지도의 제안 이력(최신순)과 오늘(KST 자정 이후) 모델을 쓴 관찰 수, 요약 갱신 판단이 보는 카테고리
    요약 메타(8절, #586), 현황 문단을 마지막으로 만들려 한 칸의 해시(8.2, #1168)."""
    rows = db.execute(
        select(AgentSuggestion).where(AgentSuggestion.map_id == map_id)
        .order_by(AgentSuggestion.created_at.desc(), AgentSuggestion.id)
    ).scalars().all()
    model_runs_today = db.execute(
        select(func.count()).select_from(AgentRun).where(
            AgentRun.map_id == map_id,
            AgentRun.used_model.is_(True),
            AgentRun.trigger.in_(MODEL_RUN_TRIGGERS),
            AgentRun.started_at >= kst_day_start(now),
        )
    ).scalar_one()
    return core.History(
        status_hash=_last_status_hash(db, map_id),
        suggestions=tuple(
            core.PastSuggestion(
                id=str(r.id), diagnosis=r.diagnosis, category=r.category, fingerprint=r.fingerprint,
                status=r.status, created_at=r.created_at, resolved_at=r.resolved_at, expires_at=r.expires_at,
                evidence_hash=r.evidence_hash,
            )
            for r in rows
        ),
        model_runs_today=model_runs_today,
        summaries=tuple(core.summary_meta(r.category, r.summary, r.updated_at) for r in list_summaries(db, map_id)),
        summary_failed=_recent_summary_failures(db, map_id, now),
    )


def _recent_summary_failures(db: Session, map_id: str, now: datetime) -> frozenset[str]:
    """최근 SUMMARY_FAILED_RETRY 안에 ②가 실패해(trigger=summary, outcome=model_failed) 요약을 못 만든 카테고리(#1187)."""
    rows = db.execute(
        select(AgentRun.outcome_detail).where(
            AgentRun.map_id == map_id, AgentRun.trigger == "summary", AgentRun.outcome == "model_failed",
            AgentRun.started_at >= now - SUMMARY_FAILED_RETRY,
        )
    ).scalars().all()
    # started_at >= now - 간격: 정확히 간격만큼 전의 실패는 아직 미룬다(경계 포함). 옛·이상 행(dict가 아니거나 category가 문자열이 아님)은 건너뛴다.
    return frozenset(d["category"] for d in rows if isinstance(d, dict) and isinstance(d.get("category"), str))


def _last_status_hash(db: Session, map_id: str) -> str | None:
    """현황 문단을 마지막으로 만들려 한 칸의 해시(8.2) — 가장 최근 status 관찰의 outcome_detail.cells_hash. 검증에서 떨어지거나
    모델이 실패한 칸도 여기 남아 같은 칸으로 다시 부르지 않는다(2절 10번). status 관찰이 보존 기한(30일)으로 지워졌으면 저장된
    문단의 칸 해시."""
    last = db.execute(
        select(AgentRun.outcome_detail).where(AgentRun.map_id == map_id, AgentRun.trigger == "status")
        .order_by(AgentRun.started_at.desc()).limit(1)
    ).scalar_one_or_none()
    if last and last.get("cells_hash"):
        return last["cells_hash"]
    return db.execute(select(AgentMapStatus.cells_hash).where(AgentMapStatus.map_id == map_id)).scalar_one_or_none()


# ---------------------------------------------------------------- 제안 상태 (12.4, 12.9)

Changed = list[tuple[str, bool]]   # 상태를 바꾼 제안의 (id, shadow)


def _changed(result) -> Changed:
    return [(str(i), shadow) for i, shadow in result.all()]


def expire_suggestions(db: Session, map_id: str, now: datetime) -> Changed:
    """expires_at이 지난 활성 제안을 expired로."""
    return _changed(db.execute(
        update(AgentSuggestion)
        .where(AgentSuggestion.map_id == map_id, AgentSuggestion.status == "active", AgentSuggestion.expires_at < now)
        .values(status="expired", resolved_at=now)
        .returning(AgentSuggestion.id, AgentSuggestion.shadow)
    ))


def supersede(db: Session, suggestion_ids: list[str], now: datetime) -> Changed:
    """신호가 사라졌거나 근거가 바뀐 활성 제안을 superseded로. 그새 사람이 처리했으면(active가 아니면) 두고, 바꾼
    것만 돌려준다."""
    if not suggestion_ids:
        return []
    return _changed(db.execute(
        update(AgentSuggestion)
        .where(AgentSuggestion.id.in_(suggestion_ids), AgentSuggestion.status == "active")
        .values(status="superseded", resolved_at=now)
        .returning(AgentSuggestion.id, AgentSuggestion.shadow)
    ))


def supersede_active(db: Session, map_id: str, now: datetime) -> Changed:
    """모드를 끄면 그 지도의 활성 제안(shadow 포함)을 superseded로(명세 12.9)."""
    return _changed(db.execute(
        update(AgentSuggestion)
        .where(AgentSuggestion.map_id == map_id, AgentSuggestion.status == "active")
        .values(status="superseded", resolved_at=now)
        .returning(AgentSuggestion.id, AgentSuggestion.shadow)
    ))


def insert_suggestion(
    db: Session, *, map_id: str, run_id: uuid.UUID, signal: core.Signal, draft: core.Draft, now: datetime,
    shadow: bool,
) -> uuid.UUID | None:
    """활성 제안 하나를 넣는다. 이미 활성 제안이 있으면 넣지 않고 None(ON CONFLICT (map_id) WHERE
    status='active' DO NOTHING — 부분 유니크 인덱스가 지도당 하나를 지킨다, 17절 8번).

    제목, 문장, 버튼은 초안(core.Draft)의 슬롯 문장과 claim 그대로 넣는다. 우리 데이터 확인(6.6)은 (pin_id, fact_key)만 넣는다.
    핀 이름, 사유 글, 라벨 값은 어디에도 넣지 않는다(명세 2절 13번) — 렌더는 응답과 이벤트를 만들 때 한다."""
    return db.execute(
        pg_insert(AgentSuggestion)
        .values(
            id=uuid.uuid4(), map_id=map_id, run_id=run_id, diagnosis=signal.diagnosis, category=signal.category,
            pin_id=uuid.UUID(signal.pin_id) if signal.pin_id else None, fingerprint=signal.fingerprint,
            evidence_hash=signal.evidence_hash, title=draft.title, claims=draft.claims, analysis=draft.analysis,
            advice=draft.advice, actions=draft.actions, facts=draft.facts,
            status="active", shadow=shadow, created_at=now, expires_at=now + SUGGESTION_TTL,
        )
        .on_conflict_do_nothing(index_elements=[AgentSuggestion.map_id], index_where=text("status = 'active'"))
        .returning(AgentSuggestion.id)
    ).scalar_one_or_none()


def recent_suggestion_facts(db: Session, map_id: str, since: datetime) -> list[list[dict]]:
    """since 이후 만든 이 지도 제안들의 facts(상태 상관없이) — 웹 확인 24시간 재사용(6.8)이 core.reusable_web으로 찾는다. 새 테이블
    없이 agent_suggestions.facts만 읽는다. 빈 facts는 뺀다."""
    rows = db.execute(
        select(AgentSuggestion.facts)
        .where(AgentSuggestion.map_id == map_id, AgentSuggestion.created_at >= since, AgentSuggestion.facts != text("'[]'::jsonb"))
    ).scalars().all()
    return [list(f) for f in rows if f]


# ---------------------------------------------------------------- 기록과 보존 (12.4, 12.9)

def insert_run(db: Session, **fields) -> uuid.UUID:
    """관찰 한 번의 기록. 칸은 models.AgentRun 그대로 받는다. id를 주지 않으면 새로 만든다(조언은 먼저 정한 id를 쓴다)."""
    row = AgentRun(**({"id": uuid.uuid4()} | fields))
    db.add(row)
    db.flush()
    return row.id


def set_run_outcome(db: Session, run_id: uuid.UUID, outcome: str, *, blocked: list[dict]) -> None:
    """제안을 넣으려다 활성 제안에 막힌 관찰(동시 저장)의 결과를 고친다."""
    db.execute(update(AgentRun).where(AgentRun.id == run_id).values(outcome=outcome, blocked=blocked))


def error_streak(db: Session, map_id: str) -> int:
    """그 지도의 가장 최근 관찰부터 이어서 예외로 끝난 관찰 수(#677). 관찰 한 번의 행들(지도 관찰, 요약, error)은 started_at
    (관찰 시각)이 같아서 관찰 단위로 묶고, error 행이 있는 관찰을 센다 — 요약 단계에서 실패하면 지도 관찰 행과 error 행이
    함께 있다. 조언(run_advice)은 관찰이 아니라 보지 않는다. 재시도 간격이 그 뒤로 같아 ERROR_RETRY_DELAYS 개수까지만 센다."""
    failed = db.execute(
        select(func.bool_or(AgentRun.outcome == "error"))
        .where(AgentRun.map_id == map_id, AgentRun.trigger != "run_advice")
        .group_by(AgentRun.started_at)
        .order_by(AgentRun.started_at.desc())
        .limit(len(ERROR_RETRY_DELAYS))
    ).scalars()
    streak = 0
    for has_error in failed:
        if not has_error:
            break
        streak += 1
    return streak


def delete_old_runs(db: Session, now: datetime) -> int:
    """보존 기한(30일)이 지난 agent_runs를 지운다. 제안의 run_id는 FK ON DELETE SET NULL로 비워진다."""
    cutoff = now - timedelta(days=AGENT_RUNS_RETENTION_DAYS)
    return db.execute(delete(AgentRun).where(AgentRun.started_at < cutoff)).rowcount


def _undecided(created_before: datetime):
    return (AgentSuggestion.decided_within_24h.is_(None), AgentSuggestion.created_at < created_before)


def list_undecided_map_ids(db: Session, *, created_before: datetime) -> list[str]:
    """decided_within_24h가 비었고 created_before보다 먼저 만든 제안이 있는 지도(12.9, #613). shadow와 상태는 보지 않는다."""
    return list(db.execute(
        select(AgentSuggestion.map_id).where(*_undecided(created_before)).distinct().order_by(AgentSuggestion.map_id)
    ).scalars())


def list_undecided(db: Session, *, map_id: str, created_before: datetime) -> list[core.DecisionTarget]:
    rows = db.execute(
        select(AgentSuggestion).where(AgentSuggestion.map_id == map_id, *_undecided(created_before))
        .order_by(AgentSuggestion.created_at, AgentSuggestion.id)
    ).scalars()
    return [
        core.DecisionTarget(id=r.id, diagnosis=r.diagnosis, category=r.category,
                            pin_id=str(r.pin_id) if r.pin_id else None, claims=r.claims, actions=r.actions,
                            created_at=r.created_at)
        for r in rows
    ]


def set_decided(db: Session, decisions: dict[uuid.UUID, bool]) -> int:
    """decided_within_24h를 채운다. 이미 채운 행은 건드리지 않는다(동시에 두 인스턴스가 정리해도 먼저 쓴 값이 남는다).
    채운 행 수."""
    filled = 0
    for value in (True, False):
        ids = [i for i, v in decisions.items() if v is value]
        if ids:
            filled += db.execute(
                update(AgentSuggestion)
                .where(AgentSuggestion.id.in_(ids), AgentSuggestion.decided_within_24h.is_(None))
                .values(decided_within_24h=value)
            ).rowcount
    return filled


# ---------------------------------------------------------------- 화면 요청 (14절)

def get_settings(db: Session, map_id: str) -> AgentSettings | None:
    return db.get(AgentSettings, map_id)


def save_settings(db: Session, *, map_id: str, enabled: bool, user_id: str, now: datetime) -> None:
    """모드 행을 덮어쓴다(없으면 만든다). 동시에 두 사람이 바꾸면 늦게 커밋한 쪽이 남는다."""
    db.execute(
        pg_insert(AgentSettings)
        .values(map_id=map_id, enabled=enabled, updated_by=user_id, updated_at=now)
        .on_conflict_do_update(
            index_elements=[AgentSettings.map_id], set_={"enabled": enabled, "updated_by": user_id, "updated_at": now},
        )
    )


def wake_cursor(db: Session, map_id: str, now: datetime) -> None:
    """모드를 다시 켜면 다음 tick에 관찰하도록 next_check_at을 지금으로(12.9). 커서 행이 없으면 만든다."""
    db.execute(
        pg_insert(AgentCursor).values(map_id=map_id, next_check_at=now)
        .on_conflict_do_update(index_elements=[AgentCursor.map_id], set_={"next_check_at": now})
    )


def get_suggestion(db: Session, suggestion_id: str) -> AgentSuggestion | None:
    try:
        key = uuid.UUID(suggestion_id)
    except ValueError:
        return None
    return db.get(AgentSuggestion, key)


def active_suggestion(db: Session, map_id: str, now: datetime) -> AgentSuggestion | None:
    """화면에 보일 지금 제안 — active이고 shadow가 아니고 만료 시각 전. 만료 처리는 관찰이 하지만(12.9) 그 전에도
    지난 제안은 보이지 않는다."""
    return db.execute(
        select(AgentSuggestion).where(
            AgentSuggestion.map_id == map_id, AgentSuggestion.status == "active",
            AgentSuggestion.shadow.is_(False), AgentSuggestion.expires_at > now,
        )
    ).scalar_one_or_none()


def has_viewed(db: Session, suggestion_id: uuid.UUID, user_id: str) -> bool:
    return db.get(AgentSuggestionView, (suggestion_id, user_id)) is not None


def record_view(db: Session, suggestion_id: uuid.UUID, user_id: str, now: datetime) -> None:
    """사람마다 한 번(멱등). 첫 열람 시각을 남긴다."""
    db.execute(
        pg_insert(AgentSuggestionView).values(suggestion_id=suggestion_id, user_id=user_id, viewed_at=now)
        .on_conflict_do_nothing(index_elements=[AgentSuggestionView.suggestion_id, AgentSuggestionView.user_id])
    )


def resolve_suggestion(
    db: Session, suggestion_id: uuid.UUID, *, status: str, user_id: str, now: datetime, action: dict | None = None,
) -> bool:
    """수락(accepted)과 닫기(dismissed). status='active'이고 만료 전일 때만 바꾸는 가드 UPDATE — 두 사람이 동시에
    누르면 늦은 쪽은 앞 트랜잭션을 기다린 뒤 조건을 다시 보고 0행이 된다. 바꿨으면 True."""
    return db.execute(
        update(AgentSuggestion)
        .where(AgentSuggestion.id == suggestion_id, AgentSuggestion.status == "active",
               AgentSuggestion.expires_at > now)
        .values(status=status, resolved_by=user_id, resolved_at=now, resolved_action=action)
        .returning(AgentSuggestion.id)
    ).first() is not None


# ---------------------------------------------------------------- 우리 조건 요약 (8절, 13절)

def upsert_summary(
    db: Session, *, map_id: str, category: str, summary: dict, run_id: uuid.UUID, now: datetime,
) -> None:
    """카테고리마다 최신본 하나만 덮어쓴다. summary는 core.summarize_reasons의 모양 그대로 — 키, 개수, reaction_id,
    문구 종류만 있고 사유 글과 구성원은 없다(명세 2절 13번). based_on_reaction_count는 그 요약이 본 사유 있는 반응 수."""
    values = {"summary": summary, "based_on_reaction_count": len(summary["reaction_ids"]), "run_id": run_id,
              "updated_at": now}
    db.execute(
        pg_insert(AgentReasonSummary).values(map_id=map_id, category=category, **values)
        .on_conflict_do_update(index_elements=[AgentReasonSummary.map_id, AgentReasonSummary.category], set_=values)
    )


def list_summaries(db: Session, map_id: str) -> list[AgentReasonSummary]:
    return list(db.execute(
        select(AgentReasonSummary).where(AgentReasonSummary.map_id == map_id).order_by(AgentReasonSummary.category)
    ).scalars().all())


# ---------------------------------------------------------------- 추천 막힘 조언 (9절, 13절)

def get_run_advice(db: Session, run_id: str, state_key: str | None = None) -> AgentRunAdvice | None:
    """그 run의 조언 행. state_key를 주면 그 결과 상태의 조언일 때만(다르면 None — 결과가 바뀌어 다시 만든다), 없으면 지금 행 그대로."""
    try:
        key = uuid.UUID(run_id)
    except ValueError:
        return None
    row = db.get(AgentRunAdvice, key, populate_existing=True)
    return row if row is not None and (state_key is None or row.state_key == state_key) else None


def insert_run_advice(
    db: Session, *, run_id: str, state_key: str, map_id: str, draft: core.AdviceDraft, agent_run_id: uuid.UUID, now: datetime,
) -> bool:
    """run당 한 행(명세 9절)에 지금 결과 상태(state_key)의 조언을 넣는다(#1103). 행이 없거나 다른 상태의 조언이면 넣고(덮고) True,
    같은 상태가 이미 있으면 그대로 두고 False — INSERT ... ON CONFLICT (run_id) DO UPDATE ... WHERE state_key IS DISTINCT FROM이라
    같은 결과에 동시에 두 요청이 와도 먼저 커밋한 하나만 남는다. 기본키가 run_id라 옛 서버의 DO NOTHING도 그대로 돈다(expand).
    빈 조언(kind 없음)도 넣어 같은 결과로는 다시 만들지 않는다. 저장은 슬롯 문장, 검증을 통과한 tool_result claim,
    버튼(근거 줄은 line_id만)뿐이다 — 근거 글과 구성원은 없다(명세 2절 13번)."""
    insert = pg_insert(AgentRunAdvice).values(
        run_id=uuid.UUID(run_id), state_key=state_key, map_id=map_id, kind=draft.kind, claims=draft.claims, advice=draft.advice,
        actions=draft.actions, agent_run_id=agent_run_id, created_at=now)
    return db.execute(
        insert.on_conflict_do_update(
            index_elements=[AgentRunAdvice.run_id],
            set_={c: insert.excluded[c] for c in ("state_key", "kind", "claims", "advice", "actions", "agent_run_id", "created_at")},
            where=AgentRunAdvice.state_key.is_distinct_from(insert.excluded.state_key),
        ).returning(AgentRunAdvice.run_id)
    ).scalar_one_or_none() is not None


# ---------------------------------------------------------------- 지도 현황 문단 (8.2, 13절)

def upsert_map_status(
    db: Session, *, map_id: str, cells: dict, cells_hash: str, states: list[dict], paragraph: str, run_id: uuid.UUID,
    now: datetime,
) -> None:
    """지도마다 최신본 하나만 덮어쓴다. 검증(core.verify_status)을 통과한 것만 온다 — 떨어진 문단은 부르지 않아 지난 행이 남는다.
    칸에는 사실(개수, D-day, 카테고리 이름)뿐이고 사유 글, 이름, 장소 이름은 없다(명세 2절 11, 13번)."""
    values = {"cells": cells, "cells_hash": cells_hash, "states": states, "paragraph": paragraph, "run_id": run_id,
              "updated_at": now}
    db.execute(
        pg_insert(AgentMapStatus).values(map_id=map_id, **values)
        .on_conflict_do_update(index_elements=[AgentMapStatus.map_id], set_=values)
    )


def get_map_status(db: Session, map_id: str) -> AgentMapStatus | None:
    return db.get(AgentMapStatus, map_id)


# ---------------------------------------------------------------- 작업 기록과 살펴본 상태 (#1297, 명세 11.3, 21.3)

def get_run(db: Session, run_id: uuid.UUID | None) -> AgentRun | None:
    """제안을 만든 관찰 행(작업 기록의 입력). 30일 정리로 지워졌으면 None."""
    return db.get(AgentRun, run_id) if run_id is not None else None


def last_observed_at(db: Session, map_id: str) -> datetime | None:
    """그 지도의 마지막 관찰 시각(agent_cursors.last_observed_at). 관찰한 적이 없으면 None."""
    return db.scalar(select(AgentCursor.last_observed_at).where(AgentCursor.map_id == map_id))


def latest_observation(db: Session, map_id: str) -> AgentRun | None:
    """trigger가 activity·time인 가장 최근 관찰 행 — 살펴본 상태의 안내 문구(core.observation_notice)가 본다."""
    return db.scalars(
        select(AgentRun).where(AgentRun.map_id == map_id, AgentRun.trigger.in_(core.OBSERVATION_TRIGGERS))
        .order_by(AgentRun.started_at.desc(), AgentRun.finished_at.desc().nulls_last()).limit(1)
    ).first()
