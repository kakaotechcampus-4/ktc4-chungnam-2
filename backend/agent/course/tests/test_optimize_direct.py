"""optimize(강한 기준선 끝까지)와 지휘 루프 — 후보, 고정, 모델 없이 도는 길, 쓸 수 없는 호출 대행, 질문 카드."""

from agent.course import core, direct, goals as G, optimize as O
from agent.course.goals import Goal
from agent.course.state import initial_state
from agent.course.tests.fixtures import ALL_OPEN, COURSE, MON, PLACES, TRUE_HOURS, TUE, WED, place, trip
from llm.schemas import CourseDirectTurn

OPEN = {p.alias: ALL_OPEN for p in PLACES}
NIGHT_D1 = Goal("night_end", "d1")                  # p6(야경)이 첫날 마지막에 오게
START = (("p6", "p1"), ("p2", "p3"), ("p4", "p5"))   # p6이 첫날 처음


def state(goals=(), course=START, hours=None):
    return initial_state(trip(), hours or OPEN, course, goals)


def turn(**action):
    return CourseDirectTurn.model_validate({"thought": "해 볼게요", "action": action})


def scripted(*actions):
    queue = [turn(**a) for a in actions]
    seen = []

    def decide(turn_input):
        seen.append(turn_input)
        return queue.pop(0)

    decide.seen = seen
    return decide


class TestOptimize:
    def test_goal_moves_the_course_and_never_adds_confirmed_violations(self):
        st = state([NIGHT_D1])
        _, cands = O.optimize(st, gateway=TRUE_HOURS, priority=[NIGHT_D1.id])
        assert G.evaluate(st.trip, cands[0].course, NIGHT_D1).met is True
        assert all(core.hard_score(c.violations)[0] <= core.hard_score(st.violations)[0] for c in cands)

    def test_without_goals_it_is_the_plain_strong_baseline_with_one_candidate(self):
        _, cands = O.optimize(state(), gateway=TRUE_HOURS)
        assert len(cands) == 1 and cands[0].candidate_id == "c1" and cands[0].priority == ()

    def test_priority_orders_vary_slightly_and_dedupe(self):
        a, b, c = Goal("night_end", "d1"), Goal("daily_walk_low"), Goal("day_light", "d2")
        assert O.priority_orders([a], []) == [(a.id,)]
        assert O.priority_orders([a, b], [b.id]) == [(b.id, a.id), (a.id, b.id)]
        assert len(O.priority_orders([a, b, c], [])) == 3 == len(set(O.priority_orders([a, b, c], [])))

    def test_candidates_have_distinct_courses_and_sequential_ids(self):
        goals = [NIGHT_D1, Goal("day_light", "d1")]
        _, cands = O.optimize(state(goals), gateway=TRUE_HOURS, priority=[g.id for g in goals])
        assert [c.candidate_id for c in cands] == [f"c{i + 1}" for i in range(len(cands))]
        assert len({c.course for c in cands}) == len(cands)

    def test_locks_are_applied_and_kept(self):
        st, cands = O.optimize(state([NIGHT_D1]), gateway=TRUE_HOURS, priority=[NIGHT_D1.id], locks={"p1": "d3"})
        assert st.locks == {"p1": "d3"}
        assert all("p1" in c.course[2] for c in cands)

    def test_unknown_hours_are_looked_up_before_climbing(self):
        known = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p6")}          # p4·p5는 모른다
        st, _ = O.optimize(state(hours=known), gateway=TRUE_HOURS)
        assert {"p4", "p5"} <= st.looked_up and st.tool_counts["get_opening_hours"] == 2


class TestDirectWithoutModel:
    def test_no_goals_never_calls_the_model_and_runs_optimize_once(self):
        calls = []
        result = direct.run_direct(state(), decide=lambda i: calls.append(i), hours=TRUE_HOURS)
        assert calls == [] and result.model_turns == 0
        assert [s.call["tool"] for s in result.steps] == ["optimize", "finish"]

    def test_goals_without_model_pick_the_best_candidate_by_code(self):
        result = direct.run_direct(state([NIGHT_D1]), decide=None, hours=TRUE_HOURS)
        assert result.model_turns == 0 and G.evaluate(result.state.trip, result.course, NIGHT_D1).met is True


class TestDirectLoop:
    def test_model_optimizes_then_finishes(self):
        decide = scripted({"tool": "optimize", "priority": [NIGHT_D1.id], "locks": []},
                          {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert [s.by for s in result.steps] == ["model", "model"] and result.model_turns == 2
        assert decide.seen[1]["candidates"][0]["goals"] == [{"id": NIGHT_D1.id, "met": True, "value": 1.0}]
        assert result.steps[0].thought == "해 볼게요"

    def test_turn_input_has_only_aliases_and_scores(self):
        decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        text = str(decide.seen)
        assert "장소P1이름" not in text and "37.56" not in text and "own-p1" not in text and "pin-p1" not in text

    def test_model_failure_turn_is_taken_over_by_code(self):
        def broken(_input):
            raise RuntimeError("timeout")
        result = direct.run_direct(state([NIGHT_D1]), decide=broken, hours=TRUE_HOURS)
        assert all(s.by == "baseline" for s in result.steps) and result.outcome in ("solved", "solved_with_checks")

    def test_finish_before_optimize_is_an_error_the_model_sees(self):
        decide = scripted({"tool": "finish", "candidate_id": "c1"}, {"tool": "optimize", "priority": [], "locks": []},
                          {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert result.steps[0].result.error == "INVALID_ID" and decide.seen[1]["last_result"]["error"] == "INVALID_ID"

    def test_unknown_goal_id_and_bad_lock_are_invalid(self):
        decide = scripted({"tool": "optimize", "priority": ["nope"], "locks": []},
                          {"tool": "optimize", "priority": [], "locks": [{"place": "p9", "day": "d1"}]},
                          {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert [s.result.error for s in result.steps[:2]] == ["INVALID_ID", "INVALID_ID"]

    def test_turns_run_out_without_finish_code_picks_best(self):
        opt = {"tool": "optimize", "priority": [NIGHT_D1.id], "locks": []}
        decide = scripted(*([opt] * 5))
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert len(result.steps) <= 5 and G.evaluate(result.state.trip, result.course, NIGHT_D1).met is True

    def test_lock_is_persistent_and_makes_old_candidates_stale(self):
        decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "lock", "place": "p1", "day": "d3"},
                          {"tool": "lock", "place": "p1", "day": "d2"}, {"tool": "finish", "candidate_id": "c1"},
                          {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert [s.result.error for s in result.steps[:4]] == [None, None, "LOCKED", "INVALID_ID"]   # 풀 수 없고, 고정 뒤 후보는 낡았다
        assert result.state.locks == {"p1": "d3"}


class TestAsk:
    def optimize_first(self):
        return {"tool": "optimize", "priority": [NIGHT_D1.id], "locks": []}

    def test_pick_course_makes_a_card_with_default(self):
        st = state([NIGHT_D1, Goal("day_light", "d1")])
        ds = direct.DirectState(st, (O.Candidate("c1", START, (), ()), O.Candidate("c2", COURSE, (), ())))
        call = turn(tool="ask_requester", kind="pick_course", options=["c2", "c1"]).action
        ds, result = direct.execute(call, ds, TRUE_HOURS)
        q = ds.questions[0]
        assert result.ok and q.default == "c2" and "둘 중 어떤 코스" in q.text and "c1:" in q.text and ds.preferred == "c2"
        assert result.data["default"] == "c2"

    def test_unanswered_default_is_used_when_the_model_never_finishes(self):
        st = state([NIGHT_D1])
        cands = (O.Candidate("c1", START, (), ()), O.Candidate("c2", START, (), ()))
        assert direct.best_candidate(st, cands, preferred="c2").candidate_id == "c2"      # 동점이면 기본 선택지
        assert direct.best_candidate(st, cands).candidate_id == "c1"

    def test_pick_course_needs_two_real_candidates(self):
        decide = scripted(self.optimize_first(), {"tool": "ask_requester", "kind": "pick_course", "options": ["c1"]},
                          {"tool": "finish", "candidate_id": "c1"})
        assert direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS).steps[1].result.error == "INVALID_MOVE"

    def test_ask_closed_day_only_for_places_with_unknown_hours(self):
        known = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p6")}           # p4·p5 모름
        st = state([NIGHT_D1], hours=known)
        decide = scripted({"tool": "ask_requester", "kind": "ask_closed_day", "subject": "p1"},
                          {"tool": "ask_requester", "kind": "ask_closed_day", "subject": "p4"},
                          {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(st, decide=decide, hours=TRUE_HOURS)
        assert result.steps[0].result.error == "INVALID_ID"
        assert result.questions[0].default == "모르겠어요" and "장소P4이름" in result.questions[0].text

    def test_third_question_is_refused_and_code_takes_the_turn(self):
        known = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p6")}
        ask = {"tool": "ask_requester", "kind": "ask_closed_day", "subject": "p4"}
        decide = scripted(ask, ask, ask, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1], hours=known), decide=decide, hours=TRUE_HOURS)
        sub = result.steps[2]
        assert len(result.questions) == 2 and sub.by == "baseline" and sub.substituted_for["error"] == "LIMIT_EXCEEDED"


def test_finish_refuses_candidate_with_more_confirmed_violations():
    st = state([NIGHT_D1])
    good = O.Candidate("c1", START, (), ())
    worse = O.Candidate("c2", START, (core.Violation("x", "closed", "confirmed", "d1", ("p1",)),), ())
    ds = direct.DirectState(st, (good, worse))
    _, result = direct.execute(turn(tool="finish", candidate_id="c2").action, ds, TRUE_HOURS)
    assert result.error == "WORSENS_HARD"
