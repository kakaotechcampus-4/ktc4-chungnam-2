"""agent_* 테이블 읽기와 쓰기. 커밋하지 않는다(커밋은 호출부의 session_scope 한 곳).

- 정리: 지도 정리(`purge_map_data`), 탈퇴(`delete_by_user`) — #513
- 관찰 흐름(#515, 명세 12.2~12.5, 12.9): 지도 고르기와 lease(`claim_maps`, `release_lease`), 커서(`advance_cursor`),
  이력(`load_history`), 제안 상태(`expire_suggestions`, `supersede`, `insert_suggestion`), 기록(`insert_run`),
  보존 정리(`delete_old_runs`)
- 화면 요청(#531, 명세 14절): 모드(`get_settings`, `save_settings`, `wake_cursor`), 지금 제안(`get_suggestion`,
  `active_suggestion`), 열람(`has_viewed`, `record_view`), 수락과 닫기(`resolve_suggestion` — status='active'일 때만
  바꾸는 가드 UPDATE), 모드 끄기(`supersede_active`)

제안 상태를 바꾸는 함수는 (id, shadow) 목록을 돌려준다. agent.resolved는 shadow가 아닌 것만 낸다(호출부).

다른 모듈 테이블은 읽지도 쓰지도 않는다. event_log는 `realtime.api.latest_seq_by_map`으로만 본다(12.2).
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, func, null, or_, select, text, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from agent import core
from agent.constants import AGENT_RUNS_RETENTION_DAYS, LEASE_SEC, SUGGESTION_TTL
from agent.models import (
    AgentCursor,
    AgentReasonSummary,
    AgentRun,
    AgentRunAdvice,
    AgentSettings,
    AgentSuggestion,
    AgentSuggestionView,
)
from realtime import api as realtime_api

MODEL_RUN_TRIGGERS = ("activity", "time", "summary")   # 모델 사용 상한이 세는 trigger(12.3)

PURGE_TABLES = (
    "agent_suggestion_views", "agent_suggestions", "agent_run_advice", "agent_reason_summaries",
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


# ---------------------------------------------------------------- 지도 고르기와 lease (12.2, 12.5)

def claim_maps(db: Session, now: datetime, *, limit: int) -> list[tuple[str, str]]:
    """관찰할 지도를 골라 lease를 잡는다. (map_id, trigger) 목록 — 새 이벤트로 잡혔으면 activity, 시간 점검으로
    잡혔으면 time. 호출부가 바로 커밋해야 lease가 다른 실행에 보인다.

    1. `realtime.api.latest_seq_by_map`으로 지도별 가장 큰 seq를 받는다. 커서 행이 없는 지도는 여기서 만든다
       (ON CONFLICT DO NOTHING — 동시에 두 실행이 만들어도 하나). 커서보다 큰 seq가 있으면 바뀐 지도다.
    2. agent_cursors만 FOR UPDATE SKIP LOCKED로 잠그고 lease_until을 올린다. maps와 event_log는 조인하지 않는다.
       모드가 꺼진 지도(agent_settings.enabled=false)는 고르지 않는다. 행이 없으면 켜짐이다."""
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

    map_ids = db.execute(
        select(AgentCursor.map_id)
        .outerjoin(AgentSettings, AgentSettings.map_id == AgentCursor.map_id)
        .where(
            func.coalesce(AgentSettings.enabled, true()),
            or_(AgentCursor.lease_until.is_(None), AgentCursor.lease_until < now),
            or_(AgentCursor.map_id.in_(changed), AgentCursor.next_check_at <= now),
        )
        .order_by(AgentCursor.next_check_at.asc().nulls_last(), AgentCursor.map_id)
        .limit(limit)
        .with_for_update(of=AgentCursor, skip_locked=True)
    ).scalars().all()
    if map_ids:
        db.execute(
            update(AgentCursor).where(AgentCursor.map_id.in_(map_ids))
            .values(lease_until=now + timedelta(seconds=LEASE_SEC))
        )
    return [(m, "activity" if m in changed else "time") for m in map_ids]


def release_lease(db: Session, map_id: str) -> None:
    db.execute(update(AgentCursor).where(AgentCursor.map_id == map_id).values(lease_until=None))


def advance_cursor(
    db: Session, map_id: str, seq: int | None, *, next_check_at: datetime | None, observed_at: datetime,
) -> None:
    """커서 = 본 것 중 가장 큰 seq(#525). 뒤로 가지 않는다 — seq가 없거나(보존 24시간 안에 이벤트 없음) 더 작으면
    그대로 둔다. 구멍은 추적하지 않는다. 행이 없으면(지도 정리가 먼저 지움) 아무것도 하지 않는다."""
    last_seen = AgentCursor.last_seen_seq if seq is None else func.greatest(AgentCursor.last_seen_seq, seq)
    db.execute(
        update(AgentCursor).where(AgentCursor.map_id == map_id)
        .values(last_seen_seq=last_seen, next_check_at=next_check_at, last_observed_at=observed_at)
    )


# ---------------------------------------------------------------- 이력 (12.3)

def load_history(db: Session, map_id: str, now: datetime) -> core.History:
    """정책이 보는 이 지도의 제안 이력(최신순), 오늘(KST 자정 이후) 모델을 쓴 관찰 수, 직전 관찰의 순위."""
    rows = db.execute(
        select(AgentSuggestion).where(AgentSuggestion.map_id == map_id)
        .order_by(AgentSuggestion.created_at.desc(), AgentSuggestion.id)
    ).scalars().all()
    model_runs_today = db.execute(
        select(func.count()).select_from(AgentRun).where(
            AgentRun.map_id == map_id,
            AgentRun.used_model.is_(True),
            AgentRun.trigger.in_(MODEL_RUN_TRIGGERS),
            AgentRun.started_at >= core.kst_day_start(now),
        )
    ).scalar_one()
    # 직전 관찰의 순위(7절 2번 재사용). summary·run_advice 행은 순위를 정하지 않아 보지 않는다
    last_priority = db.execute(
        select(AgentRun.priority).where(AgentRun.map_id == map_id, AgentRun.trigger.in_(("activity", "time")))
        .order_by(AgentRun.started_at.desc(), AgentRun.finished_at.desc().nulls_last()).limit(1)
    ).scalar_one_or_none()
    return core.History(
        suggestions=tuple(
            core.PastSuggestion(
                id=str(r.id), diagnosis=r.diagnosis, category=r.category, fingerprint=r.fingerprint,
                status=r.status, created_at=r.created_at, resolved_at=r.resolved_at, expires_at=r.expires_at,
                evidence_hash=r.evidence_hash,
            )
            for r in rows
        ),
        model_runs_today=model_runs_today,
        last_priority=last_priority,
    )


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

    제목, 문장, 버튼은 초안(core.Draft)의 슬롯 문장과 claim 그대로 넣는다. 핀 이름과 사유 글은 어디에도 넣지 않는다
    (명세 2절 13번) — 렌더는 응답과 이벤트를 만들 때 한다."""
    return db.execute(
        pg_insert(AgentSuggestion)
        .values(
            id=uuid.uuid4(), map_id=map_id, run_id=run_id, diagnosis=signal.diagnosis, category=signal.category,
            pin_id=uuid.UUID(signal.pin_id) if signal.pin_id else None, fingerprint=signal.fingerprint,
            evidence_hash=signal.evidence_hash, title=draft.title, claims=draft.claims, analysis=draft.analysis,
            advice=draft.advice, actions=draft.actions,
            status="active", shadow=shadow, created_at=now, expires_at=now + SUGGESTION_TTL,
        )
        .on_conflict_do_nothing(index_elements=[AgentSuggestion.map_id], index_where=text("status = 'active'"))
        .returning(AgentSuggestion.id)
    ).scalar_one_or_none()


# ---------------------------------------------------------------- 기록과 보존 (12.4, 12.9)

def insert_run(db: Session, **fields) -> uuid.UUID:
    """관찰 한 번의 기록. 칸은 models.AgentRun 그대로 받는다."""
    row = AgentRun(id=uuid.uuid4(), **fields)
    db.add(row)
    db.flush()
    return row.id


def set_run_outcome(db: Session, run_id: uuid.UUID, outcome: str, *, blocked: list[dict]) -> None:
    """제안을 넣으려다 활성 제안에 막힌 관찰(동시 저장)의 결과를 고친다."""
    db.execute(update(AgentRun).where(AgentRun.id == run_id).values(outcome=outcome, blocked=blocked))


def delete_old_runs(db: Session, now: datetime) -> int:
    """보존 기한(30일)이 지난 agent_runs를 지운다. 제안의 run_id는 FK ON DELETE SET NULL로 비워진다."""
    cutoff = now - timedelta(days=AGENT_RUNS_RETENTION_DAYS)
    return db.execute(delete(AgentRun).where(AgentRun.started_at < cutoff)).rowcount


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
