"""service.load_history(#515) — 정책이 보는 이력 모양(core.History)과 오늘 모델 사용 수(12.3)."""

from datetime import timedelta

from agent import core, service
from common.kst import kst_day_start
from agent.tests import rows
from agent.tests.rows import NOW


def test_history_is_newest_first_with_evidence_hash(db_session):
    old = rows.suggestion(db_session, "map_1", status="dismissed", created_at=NOW - timedelta(hours=5),
                          evidence_hash="eh-old")
    new = rows.suggestion(db_session, "map_1", status="active", created_at=NOW - timedelta(hours=1),
                          evidence_hash="eh-new")
    rows.suggestion(db_session, "map_2", status="active")

    hist = service.load_history(db_session, "map_1", NOW)

    assert [h.id for h in hist.suggestions] == [str(new.id), str(old.id)]
    assert hist.active.evidence_hash == "eh-new"


def test_model_runs_today_counts_model_runs_since_kst_midnight(db_session):
    day_start = kst_day_start(NOW)
    rows.run(db_session, "map_1", used_model=True, trigger="activity", started_at=day_start)
    rows.run(db_session, "map_1", used_model=True, trigger="summary", started_at=day_start + timedelta(hours=1))
    rows.run(db_session, "map_1", used_model=True, trigger="run_advice", started_at=day_start)   # 상한 밖
    rows.run(db_session, "map_1", used_model=False, trigger="time", started_at=day_start)
    rows.run(db_session, "map_1", used_model=True, trigger="time", started_at=day_start - timedelta(seconds=1))
    rows.run(db_session, "map_2", used_model=True, trigger="time", started_at=day_start)

    assert service.load_history(db_session, "map_1", NOW).model_runs_today == 2


# ---------------------------------------------------------------- 요약 ② 실패 이력 (#1187)

def _failed(db, detail, at):
    rows.run(db, "map_1", trigger="summary", outcome="model_failed", outcome_detail=detail, started_at=at)


def test_summary_failures_ignore_malformed_rows(db_session):
    """옛·이상 모양의 outcome_detail(리스트, 문자열, category가 문자열이 아님, 없음) 한 행이 load_history 전체를 죽이지 않는다."""
    at = NOW - timedelta(minutes=5)
    _failed(db_session, {"category": "음식점", "reason": "structure_failed"}, at)
    _failed(db_session, ["category", "카페"], at)
    _failed(db_session, "category", at)
    _failed(db_session, {"category": ["카페"]}, at)
    _failed(db_session, {"reason": "structure_failed"}, at)
    _failed(db_session, None, at)

    assert service.load_history(db_session, "map_1", NOW).summary_failed == frozenset({"음식점"})


def test_summary_failure_is_deferred_for_the_retry_window_then_retried(db_session):
    """실패한 카테고리는 SUMMARY_FAILED_RETRY 동안 뒤로 밀린다. 간격이 지나면 정상 순서로 돌아와 다시 선택된다.
    started_at >= now - 간격이라 정확히 간격 전의 실패는 아직 밀린다(경계 포함)."""
    from agent.constants import SUMMARY_FAILED_RETRY
    from agent.tests.test_core_summary import _two_due

    _failed(db_session, {"category": "음식점"}, NOW - SUMMARY_FAILED_RETRY + timedelta(seconds=1))   # 29분 59초 전
    hist = service.load_history(db_session, "map_1", NOW)
    assert hist.summary_failed == frozenset({"음식점"})
    s = _two_due()
    assert core.pick_summary(s, [], failed=hist.summary_failed)[0] == "카페"   # 다른 카테고리가 먼저

    later = NOW + timedelta(seconds=2)   # 이제 실패가 간격(30분)보다 오래됐다
    hist = service.load_history(db_session, "map_1", later)
    assert hist.summary_failed == frozenset()
    assert core.pick_summary(s, [], failed=hist.summary_failed)[0] == "음식점"   # 실패했던 카테고리가 다시 선택된다

    assert service.load_history(db_session, "map_1", NOW + timedelta(seconds=1)).summary_failed == frozenset({"음식점"})   # 경계(정확히 30분 전)는 포함
