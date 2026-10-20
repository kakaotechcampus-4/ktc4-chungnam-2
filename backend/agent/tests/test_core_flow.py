"""관찰 흐름의 순수 판단(#515) — 최근 이벤트(12.5), 관찰 실패 뒤 재시도 간격(#677), 활성 제안 무효화(12.9), 상태
재확인(12.8), 1순위(7절)."""

from dataclasses import replace
from datetime import timedelta

from agent import constants, core
from agent.tests.snaps import NOW, hours, item, pin, snap

SEC = timedelta(seconds=1)
POLICY = core.load_policy()


def _gap_snap(*confirmed):
    pins = [pin(p) for p in confirmed]
    return snap(pins=pins, shortlist=[item(p) for p in confirmed])


def _active(sig, **kw):
    return core.PastSuggestion(
        id="act", diagnosis=sig.diagnosis, category=sig.category, fingerprint=sig.fingerprint, status="active",
        created_at=NOW - hours(1), evidence_hash=sig.evidence_hash, **kw,
    )


def test_has_recent_event_boundary():
    assert core.has_recent_event(NOW - SEC, NOW) is True
    assert core.has_recent_event(NOW - 2 * SEC, NOW) is False   # 2초 '안'만
    assert core.has_recent_event(None, NOW) is False


def test_error_retry_waits_longer_with_each_consecutive_error():
    """관찰이 예외로 끝난 지도는 연속 error 1회 30분, 2회 2시간, 3회부터 6시간 뒤에 다시 본다(#677)."""
    assert [core.error_retry_at(NOW, n) - NOW for n in (1, 2, 3, 4, 10)] == [
        timedelta(minutes=30), hours(2), hours(6), hours(6), hours(6)]


def test_tick_budget_leaves_room_inside_the_lease():
    assert constants.TICK_BUDGET_SEC == constants.LEASE_SEC - 30


def test_find_superseded_keeps_active_while_signal_is_same():
    signals = core.detect_all(_gap_snap("p1", "p2"), NOW, hours(3))

    assert core.find_superseded(_active(signals[0]), signals) == []
    assert core.find_superseded(None, signals) == []


def test_find_superseded_when_signal_gone_or_evidence_changed():
    sig = core.detect_all(_gap_snap("p1", "p2"), NOW, hours(3))[0]

    assert core.find_superseded(_active(sig), []) == ["act"]
    changed = replace(sig, evidence_hash="other")
    assert core.find_superseded(_active(sig), [changed]) == ["act"]


def test_recheck_sees_same_signal_or_not():
    before = _gap_snap("p1", "p2")
    sig = core.detect_all(before, NOW, hours(3))[0]   # 카페 공백

    assert core.recheck(sig, before, NOW, hours(3)) is True
    cafe_confirmed = snap(pins=[pin("p1"), pin("p2"), pin("c1", category="카페")],
                          shortlist=[item("p1"), item("p2"), item("c1")])
    assert core.recheck(sig, cafe_confirmed, NOW, hours(3)) is False


def test_choose_top_uses_fallback_order_and_logs_it():
    gap = replace(core.make_signal("category_gap", category="카페", evidence=[], features={}), id="s1")
    stall = replace(core.make_signal("stall", category="음식점", evidence=[], features={}), id="s2")

    top, log = core.choose_top([gap, stall], POLICY)

    assert top.id == "s2"
    assert log == {"source": "rules", "final_order": ["s2", "s1"],
                   "fingerprints": [stall.fingerprint, gap.fingerprint], "rule_hits": []}
    assert core.choose_top([], POLICY) == (None, None)


def test_signal_record_has_ids_only():
    sig = core.detect_all(_gap_snap("p1", "p2"), NOW, hours(3))[0]

    rec = core.signal_record(sig)

    assert rec["evidence_ids"] == ["p1", "p2"] and rec["diagnosis"] == "category_gap"
    assert set(rec) == {"id", "diagnosis", "category", "pin_id", "evidence_ids", "features", "fingerprint",
                        "evidence_hash"}
