"""지도 현황 문단(명세 8.2, #1168) — 칸 계산(모델 없음), 먼저 볼 신호(#1749), 모델 출력의 모순 검증 다섯 가지. 순수 함수.

검증은 하나라도 걸리면 통째로 버린다(지난 문단 유지는 test_flows_status.py가 본다).
"""

from datetime import timedelta
from typing import get_args

import pytest

from agent import core
from agent.schemas import StatusOutput
from agent.tests.snaps import NOW, TODAY, hours, item, pin, react, snap
from llm.schemas import StatusState

POLICY = core.load_policy()


def _signals(s, now=NOW):
    th = core.time_threshold(s.action_times, s.map.start_date, s.today)
    return core.detect_all(s, now, th)


def _cells(s, now=NOW):
    """카드도 막힌 신호도 없는 관찰의 칸."""
    signals = _signals(s, now)
    return core.status_cells(s, signals, core.status_first_signal(signals, [], core.History(), now, POLICY), POLICY)


def _busy_snap(**kw):
    """음식점: 갈린 핀 하나(p1) + 의견 없는 핀 하나(p2, 반대 뒤에 찍어 정체는 아니다). 카페: 확정 하나(c1) + 후보 하나(c2, ♥).
    관광지: 비었음."""
    rs = [react("r1", "p1", "u1", "like", NOW - hours(30)), react("r2", "p1", "u2", "like", NOW - hours(29)),
          react("r3", "p1", "u3", "against", NOW - hours(28)), react("r4", "c2", "u2", "like", NOW - hours(27))]
    return snap(pins=[pin("p1"), pin("p2", at=NOW - hours(10)), pin("c1", category="카페"), pin("c2", category="카페")],
                reactions=rs, shortlist=[item("c1")], **kw)


# ---------------------------------------------------------------- 칸 계산

def test_cells_count_facts_per_category_without_state_names():
    cells = _cells(_busy_snap(start_date=TODAY + timedelta(days=5)))

    assert cells["dday"] == 5
    assert cells["categories"] == [
        {"category": "음식점", "confirmed": 0, "pins": 2, "split_pins": 1, "stalled": False, "unreacted_pins": 1},
        {"category": "카페", "confirmed": 1, "pins": 1, "split_pins": 0, "stalled": False, "unreacted_pins": 0},
        {"category": "관광지", "confirmed": 0, "pins": 0, "split_pins": 0, "stalled": False, "unreacted_pins": 0},
    ]
    # 상태 이름은 코드가 붙이지 않는다 — 칸의 값은 수와 참거짓뿐이다(stalled는 상태가 아니라 6.2 신호가 났는가)
    assert all(isinstance(v, (int, str)) and v not in get_args(StatusState)
               for cell in cells["categories"] for v in cell.values())


def test_first_category_follows_the_priority_rules():
    """음식점 갈림(전원 응답, weight 3)이 카테고리 공백보다 먼저다 — 7절 fallback_order 하나로 정한다."""
    cells = _cells(_busy_snap(start_date=TODAY + timedelta(days=5)))

    assert (cells["first_category"], cells["first_reason"]) == ("음식점", "의견이 갈린 핀이 있다")


def test_split_pins_ignore_the_time_condition_and_confirmed_pins():
    """♥1 🚫1, 셋 중 둘만 반응하고 방금이라 탐지는 안 되지만(6.3 시간 조건) 칸에는 갈린 핀으로 센다. 확정한 핀은 세지 않는다."""
    rs = [react("r1", "p1", "u1", "like", NOW - hours(0.1)), react("r2", "p1", "u2", "against", NOW - hours(0.1)),
          react("r3", "p2", "u1", "like", NOW - hours(0.1)), react("r4", "p2", "u2", "against", NOW - hours(0.1))]
    s = snap(pins=[pin("p1"), pin("p2")], reactions=rs, shortlist=[item("p2")])

    [food, *_] = _cells(s)["categories"]

    assert (food["split_pins"], food["confirmed"], food["pins"]) == (1, 1, 1)


def test_stalled_cell_comes_from_this_observation_signal():
    rs = [react("r1", "p1", "u2", "against", NOW - hours(20))]
    cells = _cells(snap(pins=[pin("p1")], reactions=rs))

    assert cells["categories"][0]["stalled"] is True
    assert (cells["first_category"], cells["first_reason"]) == ("음식점", "반대 뒤로 새 후보가 없다")


def test_no_signal_means_no_first_category():
    cells = _cells(snap())
    assert (cells["first_category"], cells["first_reason"]) == (None, None)


@pytest.mark.parametrize("days, reason", [(3, "출발이 가까운데 확정한 곳이 없다"), (30, "확정한 곳이 아직 없다")])
def test_category_gap_reason_says_near_only_when_it_is(days, reason):
    s = snap(pins=[pin("p1"), pin("p2")], shortlist=[item("p1"), item("p2")], start_date=TODAY + timedelta(days=days))
    cells = _cells(s)

    assert (cells["first_category"], cells["first_reason"]) == ("카페", reason)


def test_no_reaction_first_has_no_category():
    """반응 공백은 카테고리가 없다 — 이유만 있고 먼저 볼 카테고리는 null."""
    s = snap(pins=[pin(f"p{i}", by="u1") for i in range(3)])
    cells = _cells(s)

    assert (cells["first_category"], cells["first_reason"]) == (None, "아직 의견을 안 남긴 핀이 많다")


def test_hash_is_stable_and_changes_with_cells():
    a, b = _cells(_busy_snap()), _cells(_busy_snap())
    assert core.status_hash(a) == core.status_hash(b)
    assert core.status_hash(a) != core.status_hash(_cells(_busy_snap(start_date=TODAY + timedelta(days=4))))


# ---------------------------------------------------------------- 먼저 볼 신호 — 카드가 없을 때만 (#1749)

BUSY = _busy_snap(start_date=TODAY + timedelta(days=5))
SIGNALS = _signals(BUSY)
ORDER = core.fallback_order(SIGNALS, POLICY)   # 음식점 갈림(weight 3) → 반응 공백(1)


def _past(status, *, diagnosis="category_gap", category="관광지", fingerprint="fp-card", resolved_at=None, followup=None):
    return core.PastSuggestion(id="h1", diagnosis=diagnosis, category=category, fingerprint=fingerprint, status=status,
                               created_at=NOW - hours(2), resolved_at=resolved_at, followup=followup)


def _accepted(ago, *, followup="watching"):
    return _past("accepted", resolved_at=NOW - ago, followup=core.followup_record(followup, NOW - ago))


def _first(*suggestions, blocked=()):
    return core.status_first_signal(SIGNALS, list(blocked), core.History(suggestions=tuple(suggestions)), NOW, POLICY)


def test_without_a_card_first_is_the_top_of_the_priority_rules():
    assert [(s.diagnosis, s.category) for s in ORDER] == [("split", "음식점"), ("no_reaction", None)]
    assert _first() == ORDER[0]
    assert _first(_past("dismissed", resolved_at=NOW - hours(1))) == ORDER[0]   # 사람이 처리한 카드는 지금 카드가 아니다


def test_active_card_means_no_first():
    """관광지 공백 카드가 떠 있으면 음식점 갈림이 더 급해도 문단은 권하지 않는다 — 카드 한 곳이 말한다."""
    assert _first(_past("active")) is None

    cells = core.status_cells(BUSY, SIGNALS, _first(_past("active")), POLICY)
    assert (cells["first_category"], cells["first_reason"]) == (None, None)
    assert cells["categories"][0]["split_pins"] == 1   # 사실 칸은 그대로다


def test_shadow_card_counts_as_no_card(monkeypatch):
    monkeypatch.setattr(core, "SHADOW_DIAGNOSES", ("category_gap",))

    assert _first(_past("active")) == ORDER[0]


@pytest.mark.parametrize("ago, empty", [
    (timedelta(0), True),
    (core.FOLLOWUP_MIN_WAIT - timedelta(seconds=1), True),
    (core.FOLLOWUP_MIN_WAIT, False),
    (core.FOLLOWUP_MIN_WAIT + hours(1), False),
])
def test_right_after_accept_means_no_first(ago, empty):
    """수락 + FOLLOWUP_MIN_WAIT 전에는 수락한 버튼으로 움직일 시간이다. 그 뒤에는 순위대로."""
    assert _first(_accepted(ago)) == (None if empty else ORDER[0])


def test_accept_whose_watch_ended_does_not_hold_first():
    """수락 직후라도 막힌 곳이 풀려 지켜보기가 끝났으면(is_watching 아님) 순위대로."""
    assert _first(_accepted(timedelta(minutes=1), followup="resolved")) == ORDER[0]


@pytest.mark.parametrize("reason", ["duplicate", "backoff"])
def test_signals_closed_by_people_are_skipped(reason):
    assert _first(blocked=[core.Blocked(ORDER[0].id, reason)]) == ORDER[1]


@pytest.mark.parametrize("reason", ["model_cap", "daily_limit"])
def test_signals_held_by_cost_or_frequency_stay(reason):
    """비용·빈도 제한이지 덜 급하다는 판단이 아니다."""
    assert _first(blocked=[core.Blocked(ORDER[0].id, reason)]) == ORDER[0]


def test_all_closed_means_no_first():
    assert _first(blocked=[core.Blocked(s.id, "duplicate") for s in SIGNALS]) is None


def test_dismissed_card_is_not_recommended_by_the_paragraph():
    """닫은 카드와 같은 막힌 곳 — 정책(check_policy)이 막은 이유를 그대로 받아 문단도 다음 곳을 권한다."""
    top = ORDER[0]
    dismissed = _past("dismissed", diagnosis=top.diagnosis, category=top.category, fingerprint=top.fingerprint,
                      resolved_at=NOW - hours(1))
    hist = core.History(suggestions=(dismissed,))
    _, blocked = core.check_policy(SIGNALS, hist, BUSY, NOW)

    assert {b.signal_id: b.reason for b in blocked} == {top.id: "duplicate"}
    assert core.status_first_signal(SIGNALS, blocked, hist, NOW, POLICY) == ORDER[1]


# ---------------------------------------------------------------- 검증 다섯 가지

CELLS = {
    "dday": 5, "first_category": "음식점", "first_reason": "의견이 갈린 핀이 있다",
    "categories": [
        {"category": "음식점", "confirmed": 0, "pins": 2, "split_pins": 1, "stalled": False, "unreacted_pins": 1},
        {"category": "카페", "confirmed": 1, "pins": 1, "split_pins": 0, "stalled": False, "unreacted_pins": 0},
        {"category": "관광지", "confirmed": 0, "pins": 2, "split_pins": 0, "stalled": False, "unreacted_pins": 2},
    ],
}
GOOD = {
    "categories": [{"category": "음식점", "state": "split_left"}, {"category": "카페", "state": "almost"},
                   {"category": "관광지", "state": "few"}],
    "paragraph": "카페는 거의 정해졌고, 음식점은 갈린 곳 하나만 남았어요. 관광지는 아직 후보가 2곳뿐이에요. "
                 "출발이 5일 남았으니 음식점부터 보면 좋겠어요.",
}


def _verify(cells=CELLS, **change):
    return core.verify_status(StatusOutput.model_validate(GOOD | change), cells)


def test_good_paragraph_passes():
    v = _verify()

    assert v.ok and v.record["failed"] == []
    assert v.states == GOOD["categories"]
    assert v.paragraph == GOOD["paragraph"]


@pytest.mark.parametrize("categories", [
    [{"category": "음식점", "state": "split_left"}, {"category": "카페", "state": "almost"}],     # 빠뜨림
    GOOD["categories"] + [{"category": "숙소", "state": "empty"}],                               # 칸에 없음
    GOOD["categories"] + [{"category": "카페", "state": "almost"}],                              # 두 번
])
def test_1_every_category_exactly_once(categories):
    v = _verify(categories=categories)
    assert not v.ok and "categories" in v.record["failed"]


@pytest.mark.parametrize("category, state", [
    ("음식점", "decided"),     # 확정이 없고 갈린 핀이 있다
    ("음식점", "almost"),      # 확정이 없다
    ("카페", "split_left"),    # 갈린 핀이 없다
    ("카페", "stalled"),       # 멈추지 않았다
    ("관광지", "empty"),       # 후보가 있다
])
def test_2_state_must_not_contradict_facts(category, state):
    categories = [c | {"state": state} if c["category"] == category else c for c in GOOD["categories"]]
    v = _verify(categories=categories)

    assert not v.ok and v.record["states"] == [{"category": category, "state": state}]


def test_2_decided_needs_no_split_and_not_stalled():
    cells = {**CELLS, "categories": [
        {"category": "음식점", "confirmed": 2, "pins": 1, "split_pins": 1, "stalled": False, "unreacted_pins": 0},
        {"category": "카페", "confirmed": 1, "pins": 0, "split_pins": 0, "stalled": True, "unreacted_pins": 0},
        {"category": "관광지", "confirmed": 1, "pins": 0, "split_pins": 0, "stalled": False, "unreacted_pins": 0},
    ]}
    out = {"categories": [{"category": c, "state": "decided"} for c in ("음식점", "카페", "관광지")],
           "paragraph": "음식점부터 보면 좋겠어요."}

    v = core.verify_status(StatusOutput.model_validate(out), cells)

    assert [c["category"] for c in v.record["states"]] == ["음식점", "카페"]


@pytest.mark.parametrize("paragraph", [
    "카페는 거의 정해졌어요. 음식점은 후보가 3곳이에요. 음식점부터 보면 좋겠어요.",       # 칸에 없는 수(합)
    "출발이 6일 남았으니 음식점부터 보면 좋겠어요. 카페와 관광지는 천천히 봐요.",        # 틀린 D-day
])
def test_3_numbers_only_from_cells(paragraph):
    v = _verify(paragraph=paragraph)
    assert not v.ok and v.record["failed"] == ["numbers"]


@pytest.mark.parametrize("paragraph", [
    "카페는 거의 정해졌어요. 관광지는 후보가 2곳뿐이에요.",                                  # first_category가 나오지 않음
    "음식점은 갈린 곳이 남았어요. 관광지부터 보면 좋겠어요. 음식점도 봐요.",                 # 다른 카테고리를 「부터」
    "음식점부터 보면 좋겠어요. 카페를 먼저 정리해도 좋아요.",                               # 다른 카테고리를 「먼저」
    "먼저 관광지를 보고 음식점부터 봐요.",
])
def test_4_first_category_is_the_only_one_recommended_first(paragraph):
    v = _verify(paragraph=paragraph)
    assert not v.ok and v.record["failed"] == ["first_category"]


def test_4_without_first_category_no_category_is_pushed():
    cells = {**CELLS, "first_category": None, "first_reason": None}

    assert _verify(cells, paragraph="카페는 거의 정해졌고 음식점은 갈린 곳이 남았어요.").ok
    v = _verify(cells, paragraph="카페는 거의 정해졌어요. 음식점부터 보면 좋겠어요.")
    assert not v.ok and v.record["failed"] == ["first_category"]


@pytest.mark.parametrize("paragraph", [
    "카페는 거의 정해졌어요. 음식점부터 보고 확정하세요.",
    "음식점부터 보면 좋겠어요. 여기로 가세요.",
    "",
    "음식점부터 보면 좋겠어요." + " 카페는 거의 정해졌어요." * 40,   # 400자 넘음
])
def test_5_forbidden_phrases_empty_or_too_long(paragraph):
    v = _verify(paragraph=paragraph)
    assert not v.ok and "forbidden" in v.record["failed"]


def test_negative_dday_digits_are_not_in_cells():
    """여행 중(dday 0 이하)에는 날 수를 쓰지 않는다 — 칸의 값은 음수라 「2일째」 같은 숫자는 걸린다."""
    cells = {**CELLS, "dday": -2}
    v = _verify(cells, paragraph="여행 3일째예요. 음식점부터 보면 좋겠어요. 카페는 거의 정해졌어요.")
    assert not v.ok and v.record["failed"] == ["numbers"]
