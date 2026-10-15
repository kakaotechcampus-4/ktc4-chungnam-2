"""탐지기 경계(명세 6.2~6.5, 17절 4번) — 유형마다 성립 직전과 직후. 기준 시간은 3시간으로 고정한다.

충돌 종류(same_axis, different_axes, unclear)는 ②의 키와 방향이 필요한 compare_reasons(M1 도구)에서 시험한다.
"""

from datetime import timedelta

from agent import core
from agent.tests.snaps import NOW, hours, item, member, pin, react, snap

TH = hours(3)
SEC = timedelta(seconds=1)


def _diag(signals):
    return [(s.diagnosis, s.category) for s in signals]


# ---------------------------------------------------------------- stall (6.2)

def _stall_base(t0, **kw):
    """음식점 핀 f1에 u1의 🚫 하나(t0). 카페 핀 c1, c2는 활동용."""
    pins = [pin("f1"), pin("c1", category="카페"), pin("c2", category="카페")] + kw.pop("extra_pins", [])
    reactions = [react("r_against", "f1", "u1", "against", t0)] + kw.pop("extra_reactions", [])
    return snap(pins=pins, reactions=reactions, **kw)


def test_stall_by_time_only_at_boundary():
    t0 = NOW - TH

    [sig] = core.detect_stall(_stall_base(t0), NOW, TH)
    assert (sig.category, sig.features["trigger"]) == ("음식점", "time")
    assert sig.evidence_ids == ("r_against",)
    assert sig.features["elapsed_ratio"] == 1.0

    assert core.detect_stall(_stall_base(t0 + SEC), NOW, TH) == []   # 직전


def test_stall_by_activity_only():
    t0 = NOW - hours(1)
    two_actors = [react("a2", "c1", "u2", "like", t0 + SEC), react("a3", "c2", "u3", "like", t0 + SEC)]

    [sig] = core.detect_stall(_stall_base(t0, extra_reactions=two_actors), NOW, TH)
    assert sig.features["trigger"] == "activity"

    one_actor = two_actors[:1]
    assert core.detect_stall(_stall_base(t0, extra_reactions=one_actor), NOW, TH) == []


def test_stall_activity_before_t0_or_in_same_category_does_not_count():
    t0 = NOW - hours(1)
    before = [react("a2", "c1", "u2", "like", t0 - SEC), react("a3", "c2", "u3", "like", t0)]   # t0와 같으면 뒤가 아니다
    assert core.detect_stall(_stall_base(t0, extra_reactions=before), NOW, TH) == []

    same_cat = [react("a2", "f2", "u2", "like", t0 + SEC), react("a3", "f2", "u3", "like", t0 + SEC)]
    s = _stall_base(t0, extra_pins=[pin("f2", at=t0 - hours(1))], extra_reactions=same_cat)
    assert core.detect_stall(s, NOW, TH) == []


def test_stall_both_criteria_reports_activity():
    t0 = NOW - hours(4)
    actors = [react("a2", "c1", "u2", "like", t0 + SEC), react("a3", "c2", "u3", "like", t0 + SEC)]

    [sig] = core.detect_stall(_stall_base(t0, extra_reactions=actors), NOW, TH)
    assert sig.features["trigger"] == "activity"


def test_stall_premise_new_pin_in_category_after_t0():
    t0 = NOW - hours(4)
    assert core.detect_stall(_stall_base(t0, extra_pins=[pin("f2", at=t0 + SEC)]), NOW, TH) == []
    assert len(core.detect_stall(_stall_base(t0, extra_pins=[pin("f2", at=t0)]), NOW, TH)) == 1


def test_stall_premise_run_after_t0():
    t0 = NOW - hours(4)
    assert core.detect_stall(_stall_base(t0, last_run_at={"음식점": t0 + SEC}), NOW, TH) == []
    assert len(core.detect_stall(_stall_base(t0, last_run_at={"음식점": t0}), NOW, TH)) == 1
    assert len(core.detect_stall(_stall_base(t0, last_run_at={"카페": t0 + SEC}), NOW, TH)) == 1


def test_stall_premise_confirmed_in_category():
    t0 = NOW - hours(4)
    s = _stall_base(t0, extra_pins=[pin("f2", at=t0 - hours(1))], shortlist=[item("f2")])
    assert core.detect_stall(s, NOW, TH) == []


def test_stall_t0_is_latest_against_and_evidence_is_all_againsts():
    s = snap(
        pins=[pin("f1"), pin("f2")],
        reactions=[react("r1", "f1", "u1", "against", NOW - hours(5)),
                   react("r2", "f2", "u2", "against", NOW - hours(2)),   # t0 → 시간 기준 미달
                   react("r3", "f2", "u3", "like", NOW - hours(5))],
    )
    assert core.detect_stall(s, NOW, TH) == []

    [sig] = core.detect_stall(s, NOW + hours(1), TH)
    assert sig.evidence_ids == ("r1", "r2")
    assert sig.features["affected_members"] == 2


# ---------------------------------------------------------------- split (6.3)

def _split(reactions, *, members=("u1", "u2", "u3"), shortlist=()):
    return snap(members=members, pins=[pin("p1")], reactions=reactions, shortlist=shortlist)


def test_split_one_like_three_against_is_not_split():
    rs = [react("l1", "p1", "u1", "like", NOW - hours(10))] + [
        react(f"a{i}", "p1", f"u{i}", "against", NOW - hours(10)) for i in (2, 3, 4)
    ]
    assert core.detect_split(_split(rs, members=("u1", "u2", "u3", "u4")), NOW, TH) == []


def test_split_all_responded_fires_immediately():
    rs = [react("l1", "p1", "u1", "like", NOW), react("l2", "p1", "u2", "like", NOW),
          react("a3", "p1", "u3", "against", NOW)]

    [sig] = core.detect_split(_split(rs), NOW, TH)
    assert (sig.pin_id, sig.category, sig.features["trigger"]) == ("p1", "음식점", "all_responded")
    assert sig.evidence_ids == ("a3", "l1", "l2")


def test_split_by_time_at_boundary():
    last = NOW - TH
    rs = [react("l1", "p1", "u1", "like", last - hours(1)), react("a2", "p1", "u2", "against", last)]

    [sig] = core.detect_split(_split(rs), NOW, TH)
    assert sig.features["trigger"] == "time"

    assert core.detect_split(_split(rs), NOW - SEC, TH) == []   # 직전


def test_split_equal_counts_qualify_and_one_sided_does_not():
    assert len(core.detect_split(_split([react("l1", "p1", "u1", "like", NOW - hours(9)),
                                         react("a2", "p1", "u2", "against", NOW - hours(9))]), NOW, TH)) == 1
    assert core.detect_split(_split([react("l1", "p1", "u1", "like", NOW - hours(9)),
                                     react("l2", "p1", "u2", "like", NOW - hours(9))]), NOW, TH) == []
    assert core.detect_split(_split([react("a1", "p1", "u1", "against", NOW - hours(9)),
                                     react("a2", "p1", "u2", "against", NOW - hours(9))]), NOW, TH) == []


def test_split_skips_confirmed_pin():
    rs = [react("l1", "p1", "u1", "like", NOW), react("l2", "p1", "u2", "like", NOW),
          react("a3", "p1", "u3", "against", NOW)]
    assert core.detect_split(_split(rs, shortlist=[item("p1")]), NOW, TH) == []


# ---------------------------------------------------------------- no_reaction (6.4)

def _old_pins(n, *, by="u1", at=None):
    return [pin(f"p{i}", by=by, at=at or NOW - hours(10)) for i in range(n)]


def test_no_reaction_fires_when_half_or_more_unseen():
    pins = _old_pins(4)
    seen_two = [react("r0", "p0", "u2", "like", NOW), react("r1", "p1", "u2", "like", NOW)]   # 2/4 = 0.5

    [sig] = core.detect_no_reaction(snap(members=("u1", "u2"), pins=pins, reactions=seen_two), NOW, TH)
    assert sig.category is None
    assert sig.evidence_ids == ("p2", "p3")
    assert sig.features["affected_members"] == 1

    seen_three = seen_two + [react("r2", "p2", "u2", "like", NOW)]   # 1/4 < 0.5
    assert core.detect_no_reaction(snap(members=("u1", "u2"), pins=pins, reactions=seen_three), NOW, TH) == []


def test_no_reaction_needs_three_target_pins():
    assert core.detect_no_reaction(snap(members=("u1", "u2"), pins=_old_pins(2)), NOW, TH) == []
    assert len(core.detect_no_reaction(snap(members=("u1", "u2"), pins=_old_pins(3)), NOW, TH)) == 1


def test_no_reaction_excludes_own_pins():
    """u1이 찍은 핀은 u1의 대상이 아니다. u2만 있는 지도에서 u2가 찍은 핀 3개는 아무의 대상도 아니다."""
    assert core.detect_no_reaction(snap(members=("u1",), pins=_old_pins(3, by="u1")), NOW, TH) == []
    assert core.detect_no_reaction(snap(members=("u2",), pins=_old_pins(3, by="u2")), NOW, TH) == []


def test_no_reaction_counts_from_join_time():
    pins = _old_pins(3)
    joined_late = member("u2", joined_at=NOW - TH + SEC)
    assert core.detect_no_reaction(snap(members=("u1", joined_late), pins=pins), NOW, TH) == []

    joined_at_boundary = member("u2", joined_at=NOW - TH)
    assert len(core.detect_no_reaction(snap(members=("u1", joined_at_boundary), pins=pins), NOW, TH)) == 1


def test_no_reaction_counts_from_pin_creation():
    young = _old_pins(3, at=NOW - TH + SEC)
    assert core.detect_no_reaction(snap(members=("u1", "u2"), pins=young), NOW, TH) == []
    assert len(core.detect_no_reaction(snap(members=("u1", "u2"), pins=_old_pins(3, at=NOW - TH)), NOW, TH)) == 1


# ---------------------------------------------------------------- category_gap (6.5)

def test_category_gap_needs_two_confirmed():
    one = snap(pins=[pin("f1")], shortlist=[item("f1")])
    assert core.detect_category_gap(one) == []

    two = snap(pins=[pin("f1"), pin("f2")], shortlist=[item("f1"), item("f2")])
    signals = core.detect_category_gap(two)
    assert _diag(signals) == [("category_gap", "카페"), ("category_gap", "관광지")]
    assert all(s.evidence_ids == ("f1", "f2") for s in signals)


def test_category_gap_never_reports_unpinnable_categories():
    """숙소와 기타는 v1에서 핀을 만들 수 없어 영원히 공백으로 나온다 — 보지 않는다."""
    s = snap(pins=[pin("f1"), pin("c1", category="카페"), pin("s1", category="관광지")],
             shortlist=[item("f1"), item("c1"), item("s1")])
    assert core.detect_category_gap(s) == []

    s2 = snap(pins=[pin("f1"), pin("f2")], shortlist=[item("f1"), item("f2")])
    assert {c for _, c in _diag(core.detect_category_gap(s2))}.isdisjoint({"숙소", "기타"})


# ---------------------------------------------------------------- detect_all, 신호와 해시

def test_detect_all_numbers_signals_in_order():
    s = snap(pins=[pin("f1"), pin("f2")], shortlist=[item("f1"), item("f2")])

    signals = core.detect_all(s, NOW, TH)

    assert [sig.id for sig in signals] == ["s1", "s2"]


def test_fingerprint_ignores_evidence_order_and_hash_tracks_state():
    a = core.make_signal("stall", category="음식점", features={},
                         evidence=[("r2", "against", NOW), ("r1", "against", NOW)])
    b = core.make_signal("stall", category="음식점", features={},
                         evidence=[("r1", "against", NOW), ("r2", "against", NOW)])
    assert a.evidence_ids == ("r1", "r2")
    assert (a.fingerprint, a.evidence_hash) == (b.fingerprint, b.evidence_hash)

    other_cat = core.make_signal("stall", category="카페", features={}, evidence=[("r1", "against", NOW)])
    assert other_cat.fingerprint != core.make_signal("stall", category="음식점", features={},
                                                     evidence=[("r1", "against", NOW)]).fingerprint

    flipped = core.make_signal("stall", category="음식점", features={},
                               evidence=[("r1", "like", NOW), ("r2", "against", NOW)])
    edited = core.make_signal("stall", category="음식점", features={},
                              evidence=[("r1", "against", NOW + SEC), ("r2", "against", NOW)])
    assert flipped.fingerprint == a.fingerprint and flipped.evidence_hash != a.evidence_hash
    assert edited.fingerprint == a.fingerprint and edited.evidence_hash != a.evidence_hash


def test_evidence_hash_same_instant_in_other_timezone():
    kst_now = NOW.astimezone(core.KST)
    assert core.evidence_hash([("r1", "like", NOW)]) == core.evidence_hash([("r1", "like", kst_now)])


def test_signal_features_hold_no_reason_text():
    """Signal에는 id와 수만 있다 — 사유 글은 스냅샷에만 있다(명세 2절 13번)."""
    s = snap(pins=[pin("f1")], reactions=[react("r1", "f1", "u1", "against", NOW - hours(5))])
    [sig] = core.detect_stall(s, NOW, TH)
    assert set(sig.features) == {"affected_members", "elapsed_ratio", "dday", "recent_dismissals", "trigger",
                                 "category"}
    assert sig.features["dday"] == 30
