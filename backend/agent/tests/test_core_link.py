"""AI 추천·AI 코스와 엮기(명세 6.10, #1357) — 순수 함수.

- 끼워 보기 계산(core.schedule_fits): 일정 있음/없음, 실시간 핀, 휴무일, 카테고리 채움
- 일정 점검(schedule): 탐지(문제 있음/없음), 템플릿, 풀림(problem_gone), 순위(urgent_dday), decided_within_24h 제외
- 카테고리 공백의 모델 경로: 후보 핀이 있을 때만, 상한이면 템플릿, 진단 입력
- open_pin 행동 검사(🚫, closed, no_coords, 기록 없음, 확정), open_course는 모델 행동이 아니다
- 작업 기록: 조사 줄 「AI 코스 엔진으로 핀 n개를 일정에 끼워 봤어요」, 일정 점검 감지 줄. 도구 결과에 장소 이름이 없다

진단 출력은 DiagnosisOutput.model_construct로 만든다 — llm 스키마(llm/schemas.py)의 diagnosis에 category_gap, 행동에 open_pin이 아직
없다(#1358). #1358 뒤에는 model_validate로 바꾼다.
"""

import json
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from agent import core
from agent.course import core as course_core
from agent.course.intake import PinInput, build_trip
from agent.schemas import Action, AdviceLine, DiagnosisOutput, RefClaim, ToolClaim
from agent.snapshot import Schedule
from agent.tests.snaps import NOW, FAR_START, hours, item, pin, react, snap

DAYS = (FAR_START, FAR_START + timedelta(days=1))
BASE = (37.5665, 126.978)


def _at(dlat: float = 0.0, dlng: float = 0.0) -> tuple[float, float]:
    return BASE[0] + dlat, BASE[1] + dlng


def _pin_input(pin_id, *, category="음식점", at=(0.0, 0.0), day=None, order=None, live=False):
    if live:
        return PinInput(pin_id, None, "실시간 검색어", category)
    lat, lng = _at(*at)
    return PinInput(pin_id, f"place_{pin_id}", f"장소이름_{pin_id}", category, lat, lng, scheduled_date=day,
                    visit_order=order)


def _fits(confirmed, candidates, *, week=None, trip_open=None, categories=("음식점",)):
    build = build_trip([*confirmed, *candidates], list(DAYS), unknown_hours="check")
    return {r["pin_id"]: r for r in core.schedule_fits(build, candidates, week or {}, trip_open or {}, set(categories))}


# ---------------------------------------------------------------- 끼워 보기 (try_in_schedule의 계산)

def test_fit_picks_the_day_with_the_smallest_added_travel():
    confirmed = [
        _pin_input("a", at=(0, 0), day=DAYS[0], order=1), _pin_input("b", at=(0.002, 0), day=DAYS[0], order=2),
        _pin_input("c", at=(0.05, 0.05), day=DAYS[1], order=1), _pin_input("d", at=(0.052, 0.05), day=DAYS[1], order=2),
    ]
    near_day2 = _pin_input("x", category="카페", at=(0.051, 0.05))
    fit = _fits(confirmed, [near_day2])["x"]

    assert fit["day"] == "d2"
    assert fit["nearest_minutes"] is None
    assert fit["fills_gap"] is True                 # 확정 리스트에 카페가 없다
    assert fit["open"] == "unknown"                 # 영업을 모르면 지어내지 않는다
    # 이동 증가는 코스와 같은 함수(best_position, day_travel)로 잰 값이다
    trip = build_trip([*confirmed, near_day2], list(DAYS)).trip
    day = ("p3", "p4")
    k = course_core.best_position(trip, day, "p5")
    expected = course_core.day_travel(trip, [*day[:k], "p5", *day[k:]]) - course_core.day_travel(trip, day)
    assert fit["added_minutes"] == expected


def test_fit_without_dates_gives_nearest_minutes_and_trip_open():
    confirmed = [_pin_input("a", at=(0, 0)), _pin_input("b", at=(0.03, 0))]
    cand = _pin_input("x", at=(0.001, 0))
    fit = _fits(confirmed, [cand], trip_open={"place_x": "open"})["x"]

    trip = build_trip([*confirmed, cand], list(DAYS)).trip
    assert (fit["day"], fit["added_minutes"]) == (None, None)
    assert fit["nearest_minutes"] == course_core.travel_minutes(trip, "p3", "p1")
    assert fit["open"] == "open"
    assert fit["fills_gap"] is False


def test_fit_on_a_closed_day_says_closed():
    confirmed = [_pin_input("a", day=DAYS[0], order=1), _pin_input("b", at=(0.002, 0), day=DAYS[0], order=2)]
    cand = _pin_input("x", at=(0.001, 0))
    week = {"place_x": {DAYS[0].weekday(): "closed"}}
    assert _fits(confirmed, [cand], week=week)["x"]["open"] == "closed"


def test_fit_of_a_live_pin_is_no_coords():
    confirmed = [_pin_input("a"), _pin_input("b", at=(0.002, 0))]
    assert _fits(confirmed, [_pin_input("x", live=True)])["x"] == {"pin_id": "x", "no_coords": True}


def test_fit_with_no_confirmed_places_has_no_numbers():
    fit = _fits([], [_pin_input("x"), _pin_input("y", at=(0.001, 0))])["x"]
    assert (fit["day"], fit["added_minutes"], fit["nearest_minutes"]) == (None, None, None)


def test_fit_result_has_no_place_names():
    confirmed = [_pin_input("a", day=DAYS[0], order=1), _pin_input("b", at=(0.002, 0), day=DAYS[0], order=2)]
    raw = json.dumps(list(_fits(confirmed, [_pin_input("x", at=(0.001, 0)), _pin_input("y", live=True)]).values()),
                     ensure_ascii=False)
    assert "장소이름" not in raw and "실시간 검색어" not in raw


# ---------------------------------------------------------------- 일정 점검 (schedule)

def _schedule(*, closed_first=True, far=False) -> Schedule:
    """확정 2곳을 첫날에 넣은 일정. closed_first면 p1이 그 요일에 쉰다. far면 p2가 멀어 하루 이동이 길다."""
    places = (
        course_core.Place("p1", "pin_a", "place_a", "가", "음식점", *_at()),
        course_core.Place("p2", "pin_b", "place_b", "나", "관광지", *(_at(0.6, 0.6) if far else _at(0.002, 0))),
    )
    trip = course_core.Trip(places, DAYS, unknown_hours="check")
    hours_ = {"p1": {DAYS[0].weekday(): "closed" if closed_first else "open"}, "p2": {DAYS[0].weekday(): "open"}}
    return Schedule(trip=trip, course=(("p1", "p2"), ()), hours=hours_)


def _schedule_snap(schedule, **kw):
    pins = [pin("pin_a"), pin("pin_b", category="관광지")]
    return replace(snap(pins=pins, shortlist=[item("pin_a"), item("pin_b")], **kw), schedule=schedule)


def test_schedule_detects_closed_and_travel_problems():
    sigs = core.detect_schedule(_schedule_snap(_schedule(closed_first=True, far=True)))

    assert len(sigs) == 1
    sig = sigs[0]
    assert (sig.diagnosis, sig.category, sig.pin_id) == ("schedule", None, None)
    assert [p["kind"] for p in sig.features["problems"]] == ["closed", "travel"]
    assert sig.features["problems"][0] == {"kind": "closed", "day": "d1", "pin_ids": ["pin_a"]}
    assert sig.evidence_ids == ("closed:d1:pin_a", "travel:d1:pin_a+pin_b")


def test_schedule_without_problems_or_dates_sends_nothing():
    assert core.detect_schedule(_schedule_snap(_schedule(closed_first=False))) == []
    assert core.detect_schedule(_schedule_snap(None)) == []


def test_schedule_fingerprint_follows_the_problem_and_hash_the_hours():
    a = core.detect_schedule(_schedule_snap(_schedule(closed_first=True)))[0]
    b = core.detect_schedule(_schedule_snap(_schedule(closed_first=True, far=True)))[0]
    assert a.fingerprint != b.fingerprint                 # 문제가 늘면 다른 막힌 곳
    other_day = (DAYS[0].weekday() + 3) % 7
    known_more = replace(_schedule(closed_first=True), hours={"p1": {DAYS[0].weekday(): "closed", other_day: "open"}})
    c = core.detect_schedule(_schedule_snap(known_more))[0]
    assert c.fingerprint == a.fingerprint                 # 같은 문제
    assert c.evidence_hash != a.evidence_hash             # 걸린 장소의 영업이 바뀌면 무효화된다


def test_schedule_template_has_one_line_per_problem_and_the_course_button():
    sig = core.detect_schedule(_schedule_snap(_schedule(closed_first=True, far=True)))[0]
    draft = core.render_template(sig)

    assert draft.title == "일정에 다시 봐야 할 곳이 있어요"
    assert [a["type"] for a in draft.actions] == ["open_course"]
    assert draft.actions[0]["label"] == "AI 코스로 고쳐 보기"
    assert [line["slot_text"] for line in draft.advice] == ["1일차에 쉬는 날인 곳이 있어요 · {c1}", "1일차 이동이 길어요"]
    refs = core.RenderRefs(pin_names={"pin_a": "가게가"})
    row = SimpleNamespace(id="s", diagnosis="schedule", category=None, title=draft.title, claims=draft.claims,
                          analysis=None, advice=draft.advice, actions=draft.actions, created_at=NOW, expires_at=NOW)
    rendered = core.render_suggestion(row, refs)
    assert [seg.kind for seg in rendered.advice[0].segments] == ["text", "pin"]


def test_schedule_is_resolved_when_the_problem_is_gone():
    sig = core.detect_schedule(_schedule_snap(_schedule(closed_first=True)))[0]
    target = core.PastSuggestion(id="h1", diagnosis="schedule", category=None, fingerprint=sig.fingerprint,
                                 status="accepted", created_at=NOW - hours(3), resolved_at=NOW - hours(2),
                                 resolved_action_type="open_course", followup={"status": "watching"})

    fixed = core.episode_state(target, _schedule_snap(_schedule(closed_first=False)), NOW, hours(1))
    assert (fixed.status, fixed.reason) == ("resolved", "problem_gone")
    same = core.episode_state(target, _schedule_snap(_schedule(closed_first=True)), NOW, hours(1))
    assert same.status == "stuck"


def test_schedule_followup_skips_to_declaration_with_the_schedule_title():
    sig = core.detect_schedule(_schedule_snap(_schedule(closed_first=True)))[0]
    target = core.PastSuggestion(id="h1", diagnosis="schedule", category=None, fingerprint=sig.fingerprint,
                                 status="accepted", created_at=NOW - hours(3), resolved_at=NOW - hours(2),
                                 resolved_action_type="open_course", resolved_action_label="AI 코스로 고쳐 보기",
                                 followup={"status": "watching"})
    hist = core.History(suggestions=(target,))
    found = core.detect_followups(_schedule_snap(_schedule(closed_first=True)), hist, NOW, hours(1))

    assert len(found.signals) == 1
    follow = found.signals[0]
    assert core.is_declaration(follow)                   # open_course 하나뿐이라 다음 방법이 없다
    assert follow.evidence_ids == sig.evidence_ids
    draft = core.render_followup_template(follow)
    assert draft.title == "일정은 제가 해 볼 방법을 다 써 봤어요. 함께 정해 주세요" and draft.actions == []


def test_schedule_goes_first_when_departure_is_near():
    policy = core.parse_policy({"version": 2, "rules": {"urgent_dday": 3},
                                "weights": {"stall": 3, "split": 3, "category_gap": 2, "schedule": 2, "no_reaction": 1}})
    near = _schedule_snap(_schedule(closed_first=True), start_date=date(2026, 10, 16))
    schedule_sig = replace(core.detect_schedule(near)[0], id="s2")
    stall = replace(core.make_signal("stall", category="카페", evidence=[("r", "against", NOW)],
                                     features={"dday": 1, "affected_members": 1}), id="s1")
    order, hits = core.rank_signals([stall, schedule_sig], policy)
    assert [s.id for s in order] == ["s2", "s1"] and "urgent_dday" in hits


def test_schedule_is_not_a_decision_target():
    assert "schedule" not in core.DECIDED_DIAGNOSES
    assert core.is_decided("schedule", None, frozenset(), [core.Confirmation("pin_a", "음식점", NOW)]) is False


# ---------------------------------------------------------------- 카테고리 공백의 모델 경로

def _gap_snap(*, candidates=True, against=False):
    """음식점 확정 2곳, 카페 공백. candidates면 카페 미확정 핀 둘(c1에 ♥ 둘, c2에 ♥ 하나 — against면 c1에 🚫도)."""
    pins = [pin("f1"), pin("f2")]
    reactions = []
    if candidates:
        pins += [pin("c1", category="카페", at=NOW - hours(80)), pin("c2", category="카페", at=NOW - hours(70))]
        reactions = [react("r1", "c1", "u2", "like", NOW - hours(10)), react("r2", "c1", "u3", "like", NOW - hours(9)),
                     react("r3", "c2", "u2", "like", NOW - hours(8))]
        if against:
            reactions.append(react("r4", "c1", "u1", "against", NOW - hours(7)))
    ready = ("카페",) if candidates else ()   # 후보에 의견이 있으면 카페는 추천 준비가 된 것이다(#1583)
    return snap(pins=pins, reactions=reactions, shortlist=[item("f1"), item("f2")], ready_categories=ready)


def _gap_signal(s):
    return next(x for x in core.detect_all(s, NOW, hours(3)) if x.diagnosis == "category_gap" and x.category == "카페")


def test_category_gap_uses_the_model_only_with_candidates():
    with_pins = _gap_signal(_gap_snap())
    assert with_pins.features["candidate_pin_ids"] == ["c1", "c2"]
    assert core.uses_model(with_pins)
    assert core.allowed_actions(with_pins) == ("open_pin", "open_recommend", "search_place")
    without = _gap_signal(_gap_snap(candidates=False))
    assert not core.uses_model(without)
    assert core.allowed_actions(without) == ("search_place",)   # 핀이 없어 추천 준비가 안 됐다(#1583)
    # 다음 방법(6.9)은 지금처럼 템플릿이다
    assert not core.uses_model(replace(with_pins, features={**with_pins.features, "attempt": 1}))


def test_category_gap_at_the_model_cap_goes_on_as_a_template():
    s = _gap_snap()
    sig = _gap_signal(s)
    hist = core.History(model_runs_today=100)
    passed, blocked = core.check_policy([sig], hist, s, NOW)
    assert blocked == []
    assert passed[0].features["candidate_pin_ids"] == [] and not core.uses_model(passed[0])


def test_category_gap_diagnosis_input_has_candidates_with_counts():
    s = _gap_snap(against=True)
    sig = _gap_signal(s)
    inp = core.diagnosis_input(sig, s, preview={"passed_count": 4, "funnel": []})
    assert inp["diagnosis"] == "category_gap" and inp["confirmed_count"] == 2
    assert inp["candidates"] == [{"pin_id": "c1", "like": 2, "against": 1}, {"pin_id": "c2", "like": 1, "against": 0}]
    assert inp["preview"] == {"passed_count": 4}
    assert core.preview_target(sig, None) == ("카페", [])


# ---------------------------------------------------------------- open_pin 행동 검사 (11.2 6단계)

def _gap_output(sig, *actions):
    return DiagnosisOutput.model_construct(
        decision="suggest", diagnosis="category_gap", signal_id=sig.id,
        claims=[ToolClaim(id="c1", kind="tool_result", call_id="t1", path="pins.0.added_minutes", value=4),
                RefClaim(id="c2", kind="ref", object="pin", ref_id="c1")],
        advice=[AdviceLine(text="{c2}을 넣으면 이동이 {c1.value}분 늘어요", basis=["c1", "c2"], is_guess=False)],
        actions=list(actions),
    )


def _open_pin(pin_id):
    return Action.model_construct(type="open_pin", category=None, pin_ids=[pin_id], basis=["c1"])


FIT_C1 = {"pin_id": "c1", "day": "d1", "added_minutes": 4, "nearest_minutes": None, "open": "open", "fills_gap": True}


def _verify(s, out, sig, fits):
    results = {"t1": {"pins": [FIT_C1], "total": 1, "not_found": []}}
    return core.verify_diagnosis(out, sig, s, results, fits=fits)


def test_open_pin_kept_when_tried_and_fit():
    s = _gap_snap()
    sig = _gap_signal(s)
    verified = _verify(s, _gap_output(sig, _open_pin("c1")), sig, {"c1": FIT_C1})
    assert verified.outcome == "suggested"
    action = verified.draft.actions[0]
    assert (action["type"], action["label"], action["params"]["pin_ids"]) == ("open_pin", "이 핀 보기", ["c1"])
    assert verified.draft.title == "확정한 장소에 카페가 아직 없어요"


def test_open_pin_dropped_for_against_closed_no_coords_and_untried():
    s = _gap_snap(against=True)
    sig = _gap_signal(s)
    cases = {
        "against": (_open_pin("c1"), {"c1": FIT_C1}),
        "unfit": (_open_pin("c2"), {"c2": FIT_C1 | {"pin_id": "c2", "open": "closed"}}),
        "not_tried": (_open_pin("c2"), {}),
    }
    for reason, (action, fits) in cases.items():
        verified = _verify(s, _gap_output(sig, action), sig, fits)
        assert verified.record["actions"]["removed"] == [{"index": 0, "reason": reason}], reason
    no_coords = _verify(s, _gap_output(sig, _open_pin("c2")), sig, {"c2": {"pin_id": "c2", "no_coords": True}})
    assert no_coords.record["actions"]["removed"] == [{"index": 0, "reason": "unfit"}]


def test_open_pin_not_for_confirmed_or_other_category_pins_and_open_course_not_for_the_model():
    s = _gap_snap()
    sig = _gap_signal(s)
    out = _gap_output(sig, _open_pin("f1"),
                      Action.model_construct(type="open_course", category=None, pin_ids=None, basis=["c1"]))
    verified = _verify(s, out, sig, {"f1": FIT_C1 | {"pin_id": "f1"}})
    assert verified.record["actions"]["removed"] == [{"index": 0, "reason": "pin"}, {"index": 1, "reason": "type"}]


@pytest.mark.parametrize("basis", [[], ["c9"]])
def test_open_pin_basis_is_filled_from_its_try_in_schedule_result(basis):
    """open_pin의 근거는 그 핀의 try_in_schedule 결과다(#1380). 기록이 없으면 지금처럼 뺀다."""
    s = _gap_snap()
    sig = _gap_signal(s)
    action = Action.model_construct(type="open_pin", category=None, pin_ids=["c1"], basis=basis)
    results = {"t1": {"pins": [FIT_C1], "total": 1, "not_found": []}}
    calls = [{"call_id": "t1", "name": "try_in_schedule"}]

    filled = core.verify_diagnosis(_gap_output(sig, action), sig, s, results, fits={"c1": FIT_C1}, calls=calls)
    assert [a["type"] for a in filled.draft.actions] == ["open_pin"] and filled.record["basis_filled"] == 1
    assert filled.draft.claims[-1] == {"id": "c3", "kind": "tool_result", "call_id": "t1", "path": "pins.0.pin_id",
                                       "value": "c1"}

    missing = core.verify_diagnosis(_gap_output(sig, action), sig, s, results, fits={"c1": FIT_C1})
    assert missing.record["actions"]["removed"] == [{"index": 0, "reason": "basis"}]


def test_schedule_fits_of_reads_only_try_in_schedule_calls():
    calls = [
        {"call_id": "t1", "name": "get_reasons", "result": {"reasons": [{"pin_id": "c1"}]}},
        {"call_id": "t2", "name": "try_in_schedule", "result": {"pins": [FIT_C1]}},
        {"call_id": "t3", "name": "try_in_schedule", "result": {"error": "NOT_FOUND"}},
    ]
    assert core.schedule_fits_of(calls) == {"c1": FIT_C1}


# ---------------------------------------------------------------- 작업 기록 (11.3)

def test_steps_show_the_course_engine_line_and_the_schedule_detection():
    gap_run = SimpleNamespace(
        priority={"source": "single"}, verification=None,
        signals=[{"fingerprint": "fp", "diagnosis": "category_gap", "category": "카페", "evidence_ids": ["f1", "f2"]}],
        tool_calls=[{"call_id": "t1", "name": "try_in_schedule", "args": {"pin_ids": ["c1", "c2"]},
                     "result": {"pins": [FIT_C1, {"pin_id": "c2", "no_coords": True}], "total": 2}}],
    )
    texts = [st.text for st in core.render_steps(gap_run, SimpleNamespace(fingerprint="fp", facts=[]))]
    assert "AI 코스 엔진으로 핀 2개를 일정에 끼워 봤어요" in texts

    sig = core.detect_schedule(_schedule_snap(_schedule(closed_first=True, far=True)))[0]
    schedule_run = SimpleNamespace(priority={"source": "single"}, verification=None, tool_calls=[],
                                   signals=[core.signal_record(sig)])
    steps = core.render_steps(schedule_run, SimpleNamespace(fingerprint=sig.fingerprint, facts=[]))
    assert [(st.stage, st.text) for st in steps][0] == ("감지", "AI 코스 점검으로 확정 일정을 봤어요 · 다시 볼 곳 2개")
