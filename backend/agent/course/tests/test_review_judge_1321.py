"""점검 판단 연결(#1321 PR C) — 모델의 review 판단을 order·worth 훅에 잇는다. 모델은 스텁 planner라 실호출이 없다.

확인할 것: 하드 문제는 모델이 무엇을 내도 카드가 나온다 · 잘못된 별칭과 모순된 이유는 코드 기본으로 이어진다 · 호출 수는 상한 안이다 ·
모델이 실패하면 응답이 코드 기본과 같다."""

import json
from datetime import date

from agent.course import cards, core, direct, review, worklog
from agent.course.constants import DIRECT_MAX_TURNS
from agent.course.gateways import NullOpeningHours
from agent.course.intake import PinInput, build_trip
from agent.course.runner import run_course
from agent.course.tests.fixtures import ALL_OPEN, COURSE, MON, TUE, WED, trip
from llm.schemas import CourseDirectTurn, CourseGoal, CourseGoalSet, CourseReviewCall

HOURS = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p4", "p5", "p6")}
DAYS = (TUE, MON, TUE, MON, WED, WED)         # 둘째 날(화)에 실내 장소가 없다(실내는 2·4·6번)
FORBIDDEN = ("장소", "pin-", "own-", "37.5", "126.9")      # 이름·id·좌표


def goal_unmet_trip():
    """둘째 날 실내 위주 목표가 안 지켜진 일정 — 선호 문제 1개(날 맞바꾸기로 풀림)."""
    pins = [PinInput(f"pin-{i}", f"own-{i}", f"장소{i}", ("관광지", "카페", "음식점")[i % 3], 37.5665 + i * 0.001, 126.978 + i * 0.001,
                     frozenset({"is_indoor"}) if i % 2 == 0 else frozenset({"is_outdoor"}),
                     scheduled_date=DAYS[i - 1], visit_order=1 + (i - 1) % 2)
            for i in range(1, 7)]
    return build_trip(pins, (MON, TUE, WED), unknown_hours="check")


def goals_planner(_input):
    return CourseGoalSet(goals=[CourseGoal(kind="day_indoor", day="d2", places=[], source="request", quote="둘째 날은 실내 위주로")], unmatched=[])


def scripted(*actions, seen=None):
    queue = list(actions)

    def planner(turn_input):
        if seen is not None:
            seen.append(json.loads(json.dumps(turn_input, default=list)))
        return CourseDirectTurn.model_validate(queue.pop(0))

    return planner


OPT = {"thought": "짜 볼게요", "action": {"tool": "optimize", "priority": ["day_indoor:d2"], "locks": []}}
FIN = {"thought": "끝낼게요", "action": {"tool": "finish", "candidate_id": "c1"}}


def review_turn(**kw):
    return {"thought": "점검 판단", "action": {"tool": "review", "order": kw.get("order", []), "verdicts": kw.get("verdicts", []), "picks": []}}


def run(planner):
    return run_course(goal_unmet_trip(), "둘째 날은 실내 위주로 가고 싶어요", goals_planner=goals_planner, direct_planner=planner, gateway=NullOpeningHours())


def card(done, kind="goal"):
    return next(f for f in done.view.fixes if f["kind"] == kind)


# ---------------------------------------------------------------- 입력

def test_judge_input_has_aliases_only_and_none_when_nothing_to_judge():
    t = trip()
    result = review.review(t, COURSE, HOURS)
    judge = review.judge_input(result)
    if judge is not None:
        text = json.dumps(judge.payload, ensure_ascii=False)
        assert all(w not in text for w in FORBIDDEN)
        for row in judge.payload["problems"]:
            assert row["alias"].startswith("q") and row["strength"] in ("hard", "soft")
            for o in row["options"]:
                assert set(o) == {"no", "moved", "solves", "remaining"} and all(a in judge.aliases for a in (*o["solves"], *o["remaining"]))
    clean = review.review(t, (("p1", "p3"), ("p4", "p2"), ("p5", "p6")), HOURS)
    assert review.judge_input(clean) is None


def test_review_input_reaches_the_model_until_the_judgment_is_taken():
    seen = []
    done = run(scripted(review_turn(), OPT, FIN, seen=seen))
    assert "review" in seen[0] and "review" not in seen[1] and "review" not in seen[2]
    assert done.view.mode == "review"


def test_plan_mode_input_has_no_review_and_tool_is_a_failed_result():
    seen = []
    out = build_trip(
        [PinInput(f"pin-{i}", f"own-{i}", f"장소{i}", "관광지", 37.5665 + i * 0.001, 126.978) for i in range(1, 7)], (MON, TUE, WED), unknown_hours="check")
    run_course(out, "", goals_planner=goals_planner, direct_planner=scripted(review_turn(), OPT, FIN, seen=seen), gateway=NullOpeningHours())
    assert all("review" not in s for s in seen)


# ---------------------------------------------------------------- 판단 → 카드

def test_keep_verdict_turns_into_a_server_sentence_and_the_card_has_no_moves():
    base = run(None)
    assert card(base)["moves"] and card(base)["not_fixed_reason"] is None
    verdict = {"problem": "q1", "worth": "keep", "reason": "MINOR_GAIN"}
    done = run(scripted(review_turn(order=["q1"], verdicts=[verdict]), OPT, FIN))
    kept = card(done)
    assert kept["moves"] == [] and kept["not_fixed_reason"] == cards.NOT_FIXED_TEXT["MINOR_GAIN"]
    lines = [s["text"] for s in done.view.steps if s["stage"] == "판단"]
    assert lines and all(s["by"] == "ai" and s["role"] == "지휘" for s in done.view.steps if s["stage"] == "판단")


def test_fix_verdict_keeps_the_code_default_card():
    base = run(None)
    done = run(scripted(review_turn(verdicts=[{"problem": "q1", "worth": "fix", "reason": "FIXES_REQUEST"}]), OPT, FIN))
    assert card(done) == card(base)


def test_bad_alias_and_contradicting_reason_fall_back_to_code_default():
    base = run(None)
    bad = [{"problem": "q99", "worth": "keep", "reason": "MINOR_GAIN"},
           {"problem": "q1", "worth": "keep", "reason": "LEAVES_PROBLEMS"}]       # 안을 따라도 남는 문제가 없어 모순
    done = run(scripted(review_turn(order=["q42"], verdicts=bad), OPT, FIN))
    assert done.view.fixes == base.view.fixes
    assert [s["text"] for s in done.view.steps if s["stage"] == "대행"] == [worklog.JUDGMENT_FAILED_TEXT]


class ClosedP1:
    """p1이 화요일(둘째 날)에 쉰다 — 일정에 하드 문제(쉬는 날)가 생긴다."""

    def get_opening_hours(self, place_ids):
        return {pid: ({**ALL_OPEN, TUE.weekday(): "closed"} if pid == "own-1" else dict(ALL_OPEN)) for pid in place_ids}


def test_hard_problem_card_is_made_whatever_the_model_says():
    def go(planner):
        return run_course(goal_unmet_trip(), "둘째 날은 실내 위주로 가고 싶어요", goals_planner=goals_planner, direct_planner=planner, gateway=ClosedP1())

    base = go(None)
    assert [f["kind"] for f in base.view.fixes][:1] == ["closed"]
    seen = []
    # q1은 하드(쉬는 날), q2는 선호 — 모델이 하드까지 「그대로」로 내고 순서에서도 하드를 앞뒤로 흔든다
    verdicts = [{"problem": "q1", "worth": "keep", "reason": "MINOR_GAIN"}, {"problem": "q2", "worth": "keep", "reason": "MINOR_GAIN"}]
    done = go(scripted(review_turn(order=["q2", "q1"], verdicts=verdicts), OPT, FIN, seen=seen))
    assert "review" in seen[0]
    assert done.view.fixes[0] == base.view.fixes[0] and done.view.fixes[0]["strength"] == "hard" and done.view.fixes[0]["moves"]


def test_rejudge_never_touches_hard_fixes_even_with_a_hostile_hook():
    t = trip()
    base = review.review(t, COURSE, {**HOURS, "p4": {**ALL_OPEN, TUE.weekday(): "closed", WED.weekday(): "closed"}})
    hostile = review.rejudge(base, order=lambda soft: list(reversed(soft)), worth=lambda p, f: "MINOR_GAIN")
    assert [f for f in hostile.fixes if f.problem.strength == "hard"] == [f for f in base.fixes if f.problem.strength == "hard"]
    assert [f.problem.strength for f in hostile.fixes] == sorted((f.problem.strength for f in hostile.fixes), key=lambda x: x != "hard")


# ---------------------------------------------------------------- 호출 수, 실패

def test_model_calls_stay_within_the_cap():
    seen = []
    run(scripted(review_turn(), OPT, FIN, seen=seen))
    assert len(seen) <= DIRECT_MAX_TURNS


def test_model_failure_gives_the_code_default_response():
    base = run(None)

    def failing(_input):
        raise RuntimeError("boom")

    done = run(failing)
    assert done.view.fixes == base.view.fixes and done.view.headline == base.view.headline
    assert worklog.JUDGMENT_FAILED_TEXT in [s["text"] for s in done.view.steps]


def test_no_model_leaves_no_judgment_lines():
    done = run(None)
    assert not [s for s in done.view.steps if s["stage"] in ("판단", "대행")]
