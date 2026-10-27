"""api.delete_by_user(#155, 명세 12.9·17절 16번) — 탈퇴한 사람의 사유 원문이 agent_runs와 요약에 남지 않고,
그 사람의 열람 기록이 지워진다. 그 사람이 없던 지도는 건드리지 않는다."""

from sqlalchemy import select

from agent import api
from agent.models import AgentReasonSummary, AgentRun, AgentSuggestionView
from agent.tests import rows

REASON_TEXT = "너무 매워서 못 먹어요"
TOOL_CALLS = [{
    "call_id": "t1", "tool": "get_reasons", "input": {"category": "음식점"},
    "result": [{"reaction_id": "r1", "type": "against", "text": REASON_TEXT, "member_alias": "m1"}],
}]
VERIFICATION = {"claims": [{"id": "c1", "kind": "quote", "text": REASON_TEXT, "passed": True}]}


def _seed(db):
    mine = rows.run(db, "mine", tool_calls=TOOL_CALLS, verification=VERIFICATION, outcome="suggested")
    quiet = rows.run(db, "mine")  # 비울 것이 없는 run
    other = rows.run(db, "other", tool_calls=TOOL_CALLS, verification=VERIFICATION, outcome="suggested")
    rows.summary(db, "mine", "음식점", summary={"vague_fixable": {"quotes": [REASON_TEXT]}})
    rows.summary(db, "mine", "카페")
    rows.summary(db, "other", "음식점", summary={"vague_fixable": {"quotes": [REASON_TEXT]}})
    s_mine = rows.suggestion(db, "mine", run_id=mine.id)
    s_other = rows.suggestion(db, "other", run_id=other.id)
    s_deleted_map = rows.suggestion(db, "deleted_map")  # lock_member_maps가 돌려주지 않는 지도
    for s in (s_mine, s_other, s_deleted_map):
        rows.view(db, s.id, "leaver")
        rows.view(db, s.id, "stayer")
    return mine, quiet, other


def test_reason_text_is_gone_from_runs_and_summaries_of_given_maps(db_session):
    mine, quiet, other = _seed(db_session)

    result = api.delete_by_user(db_session, user_id="leaver", map_ids=["mine"])

    assert result == {"agent_suggestion_views": 3, "agent_reason_summaries": 2, "agent_runs": 1}
    db_session.expire_all()
    mine_run = db_session.get(AgentRun, mine.id)
    assert mine_run.tool_calls == [] and mine_run.verification is None
    assert mine_run.outcome == "suggested"  # 행과 지표는 남는다
    assert db_session.get(AgentRun, quiet.id) is not None
    summaries = db_session.execute(select(AgentReasonSummary.map_id)).scalars().all()
    assert summaries == ["other"]
    # 남은 agent_runs·요약 어디에도 비운 지도의 원문이 없다
    leftover = db_session.execute(
        select(AgentRun.tool_calls, AgentRun.verification).where(AgentRun.map_id == "mine")
    ).all()
    assert REASON_TEXT not in repr(leftover)


def test_other_maps_are_untouched(db_session):
    _, _, other = _seed(db_session)

    api.delete_by_user(db_session, user_id="leaver", map_ids=["mine"])

    db_session.expire_all()
    other_run = db_session.get(AgentRun, other.id)
    assert other_run.tool_calls == TOOL_CALLS and other_run.verification == VERIFICATION


def test_views_of_that_user_are_gone_everywhere_and_others_stay(db_session):
    _seed(db_session)

    api.delete_by_user(db_session, user_id="leaver", map_ids=["mine"])

    viewers = db_session.execute(select(AgentSuggestionView.user_id)).scalars().all()
    assert sorted(viewers) == ["stayer"] * 3


def test_no_maps_still_deletes_views(db_session):
    _seed(db_session)

    result = api.delete_by_user(db_session, user_id="leaver", map_ids=[])

    assert result == {"agent_suggestion_views": 3, "agent_reason_summaries": 0, "agent_runs": 0}
