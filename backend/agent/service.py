"""agent_* 테이블 읽기와 쓰기. 커밋하지 않는다(커밋은 호출부의 session_scope 한 곳).

M0(#513)은 정리 두 가지만 있다 — 지도 정리(`purge_map_data`)와 탈퇴(`delete_by_user`). 관찰 흐름이 쓰는 함수
(claim_maps, insert_run, insert_suggestion 등)는 #515에서 더한다.
"""

from sqlalchemy import delete, func, null, select, update
from sqlalchemy.orm import Session

from agent.models import (
    AgentCursor,
    AgentReasonSummary,
    AgentRun,
    AgentRunAdvice,
    AgentSettings,
    AgentSuggestion,
    AgentSuggestionView,
)

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
