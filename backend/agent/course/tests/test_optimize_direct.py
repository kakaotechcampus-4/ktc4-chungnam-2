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


def acts(result):
    """모델·기준선이 둔 단계(0번 check_goals 단계는 뺀다)."""
    return [s for s in result.steps if s.turn > 0]


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

    def test_base_and_focus_orders(self):
        a, b, c = Goal("night_end", "d1"), Goal("daily_walk_low"), Goal("day_light", "d2")
        assert O.base_order([a, b, c], [c.id]) == (c.id, a.id, b.id)
        assert O.focus_order((c.id, a.id, b.id), b.id) == (b.id, c.id, a.id)

    def test_contradicting_goals_give_diverging_candidates_with_focus(self):
        goals = [Goal("place_on_day", "d1", ("p1",)), Goal("place_on_day", "d2", ("p1",))]    # 한 장소를 두 날에 — 둘 다는 불가능
        st, cands = O.optimize(state(goals), gateway=TRUE_HOURS, priority=[g.id for g in goals])
        vectors = [O.met_vector(st, c.course) for c in cands]
        assert len(cands) == 2 and len(set(vectors)) == 2
        assert cands[0].focus is None and cands[1].focus is not None
        assert {tuple(v) for v in vectors} == {(True, False), (False, True)}

    def test_candidates_with_same_met_vector_are_merged(self):
        goals = [NIGHT_D1, Goal("day_light", "d1")]
        st, cands = O.optimize(state(goals), gateway=TRUE_HOURS, priority=[g.id for g in goals])
        vectors = [O.met_vector(st, c.course) for c in cands]
        assert len(vectors) == len(set(vectors))

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


class TestDayHasOptimize:
    def tagged_state(self, tag_on="p2", course=START):
        places = tuple(place(p.alias, p.category, p.lat, p.lng, ("performance",) if p.alias == tag_on else ("quiet",)) for p in PLACES)
        return initial_state(trip(places=places), OPEN, course, [Goal("day_has", "d3", (), "performance")])

    def test_optimize_puts_a_tagged_place_on_the_day_when_possible(self):
        st = self.tagged_state()
        goal = st.goals[0]
        assert G.evaluate(st.trip, st.course, goal).met is False
        _, cands = O.optimize(st, gateway=TRUE_HOURS, priority=[goal.id])
        assert G.evaluate(st.trip, cands[0].course, goal).met is True
        assert all(core.hard_score(c.violations)[0] <= core.hard_score(st.violations)[0] for c in cands)

    def test_no_tagged_place_stays_unmet_and_is_reported_not_invented(self):
        st = self.tagged_state(tag_on="none")
        goal = st.goals[0]
        result = direct.run_direct(st, decide=None, hours=TRUE_HOURS)
        assert result.checks[0]["reasons"] == [G.NO_TAGGED_PLACE]
        assert [r.met for r in result.goal_results] == [False]
        assert {p for d in result.chosen.course for p in d} == {p.alias for p in st.trip.places}      # 장소를 더하거나 빼지 않는다

    def test_model_input_carries_the_tag(self):
        st = self.tagged_state()
        decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        direct.run_direct(st, decide=decide, hours=TRUE_HOURS)
        assert decide.seen[0]["goals"][0] == {"id": "day_has:d3:performance", "kind": "day_has", "day": "d3", "places": [], "tag": "performance"}


class TestDirectWithoutModel:
    def test_no_goals_never_calls_the_model_and_runs_optimize_once(self):
        calls = []
        result = direct.run_direct(state(), decide=lambda i: calls.append(i), hours=TRUE_HOURS)
        assert calls == [] and result.model_turns == 0
        assert [s.call["tool"] for s in acts(result)] == ["optimize", "finish"]

    def test_goals_without_model_pick_the_best_candidate_by_code(self):
        result = direct.run_direct(state([NIGHT_D1]), decide=None, hours=TRUE_HOURS)
        assert result.model_turns == 0 and G.evaluate(result.state.trip, result.course, NIGHT_D1).met is True


class TestDirectLoop:
    def test_model_optimizes_then_finishes(self):
        decide = scripted({"tool": "optimize", "priority": [NIGHT_D1.id], "locks": []},
                          {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert [s.by for s in acts(result)] == ["model", "model"] and result.model_turns == 2
        assert decide.seen[1]["candidates"][0]["goals"] == [{"id": NIGHT_D1.id, "met": True, "value": 1.0}]
        assert acts(result)[0].thought == "해 볼게요"

    def test_turn_input_has_only_aliases_and_scores(self):
        decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        text = str(decide.seen)
        assert "장소P1이름" not in text and "37.56" not in text and "own-p1" not in text and "pin-p1" not in text

    def test_model_failure_turn_is_taken_over_by_code(self):
        def broken(_input):
            raise RuntimeError("timeout")
        result = direct.run_direct(state([NIGHT_D1]), decide=broken, hours=TRUE_HOURS)
        assert all(s.by == "baseline" for s in acts(result)) and result.outcome in ("solved", "solved_with_checks")

    def test_finish_before_optimize_is_an_error_the_model_sees(self):
        decide = scripted({"tool": "finish", "candidate_id": "c1"}, {"tool": "optimize", "priority": [], "locks": []},
                          {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert acts(result)[0].result.error == "INVALID_ID" and decide.seen[1]["last_result"]["error"] == "INVALID_ID"

    def test_unknown_goal_id_and_bad_lock_are_invalid(self):
        decide = scripted({"tool": "optimize", "priority": ["nope"], "locks": []},
                          {"tool": "optimize", "priority": [], "locks": [{"place": "p9", "day": "d1"}]},
                          {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert [s.result.error for s in acts(result)[:2]] == ["INVALID_ID", "INVALID_ID"]

    def test_turns_run_out_without_finish_code_picks_best(self):
        opt = {"tool": "optimize", "priority": [NIGHT_D1.id], "locks": []}
        decide = scripted(*([opt] * 5))
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert len(acts(result)) <= 5 and G.evaluate(result.state.trip, result.course, NIGHT_D1).met is True

    def test_lock_is_persistent_and_makes_old_candidates_stale(self):
        decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "lock", "place": "p1", "day": "d3"},
                          {"tool": "lock", "place": "p1", "day": "d2"}, {"tool": "finish", "candidate_id": "c1"},
                          {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert [s.result.error for s in acts(result)[:4]] == [None, None, "LOCKED", "INVALID_ID"]   # 풀 수 없고, 고정 뒤 후보는 낡았다
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
        assert result.ok and q.default == "c2" and q.text.startswith("A: ") and " / B: " in q.text and q.text.endswith("어느 쪽?")
        assert "하루 최대" in q.text and ds.preferred == "c2"
        assert result.data["default"] == "c2"

    def test_unanswered_default_is_used_when_the_model_never_finishes(self):
        st = state([NIGHT_D1])
        cands = (O.Candidate("c1", START, (), ()), O.Candidate("c2", START, (), ()))
        assert direct.best_candidate(st, cands, preferred="c2").candidate_id == "c2"      # 동점이면 기본 선택지
        assert direct.best_candidate(st, cands).candidate_id == "c1"

    def test_pick_course_needs_two_real_candidates(self):
        decide = scripted(self.optimize_first(), {"tool": "ask_requester", "kind": "pick_course", "options": ["c1"]},
                          {"tool": "finish", "candidate_id": "c1"})
        assert direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS).steps[2].result.error == "INVALID_MOVE"

    def test_ask_closed_day_only_for_places_with_unknown_hours(self):
        known = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p6")}           # p4·p5 모름
        st = state([NIGHT_D1], hours=known)
        decide = scripted({"tool": "ask_requester", "kind": "ask_closed_day", "subject": "p1"},
                          {"tool": "ask_requester", "kind": "ask_closed_day", "subject": "p4"},
                          {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(st, decide=decide, hours=TRUE_HOURS)
        assert acts(result)[0].result.error == "INVALID_ID"
        assert result.questions[0].default == "모르겠어요" and "장소P4이름" in result.questions[0].text

    def test_third_question_is_refused_and_code_takes_the_turn(self):
        known = {p: ALL_OPEN for p in ("p1", "p2", "p3", "p6")}
        ask = {"tool": "ask_requester", "kind": "ask_closed_day", "subject": "p4"}
        decide = scripted(ask, ask, ask, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1], hours=known), decide=decide, hours=TRUE_HOURS)
        sub = acts(result)[2]
        assert len(result.questions) == 2 and sub.by == "baseline" and sub.substituted_for["error"] == "LIMIT_EXCEEDED"


def test_finish_refuses_candidate_with_more_confirmed_violations():
    st = state([NIGHT_D1])
    good = O.Candidate("c1", START, (), ())
    worse = O.Candidate("c2", START, (core.Violation("x", "closed", "confirmed", "d1", ("p1",)),), ())
    ds = direct.DirectState(st, (good, worse))
    _, result = direct.execute(turn(tool="finish", candidate_id="c2").action, ds, TRUE_HOURS)
    assert result.error == "WORSENS_HARD"


# ---- 코드가 여는 질문, check_goals, 작업 기록 ----

def cand(cid, course, violations=()):
    return O.Candidate(cid, course, violations, ())


class TestAskTrigger:
    def setup_method(self):
        self.goals = [NIGHT_D1, Goal("day_light", "d1")]
        self.st = state(self.goals)
        # c1은 야경만, c2는 여유만 지킨다(목표가 갈린다). c3는 c1과 같은 met 벡터
        # day_light 한도는 하루 1곳(6곳÷3일−1), 라벨이 있는 장소는 p6(야경)뿐이다
        self.c1 = cand("c1", (("p1", "p2", "p6"), ("p3", "p4"), ("p5",)))          # 야경 충족, d1이 3곳이라 여유 미충족
        self.c2 = cand("c2", (("p5",), ("p1", "p2", "p3"), ("p4", "p6")))          # d1 마지막 라벨 모름 → 야경 판단 불가, d1 1곳 → 여유 충족

    def ds(self, candidates, calls=2, questions=()):
        return direct.DirectState(self.st, tuple(candidates), tuple(questions), optimize_calls=calls)

    def test_conditions_all_needed(self):
        met = [r.met for r in G.evaluate_all(self.st.trip, self.c1.course, self.goals)]
        met2 = [r.met for r in G.evaluate_all(self.st.trip, self.c2.course, self.goals)]
        assert met == [True, False] and met2 == [None, True]
        assert direct.ask_trigger(self.ds([self.c1, self.c2])) is not None
        assert direct.ask_trigger(self.ds([self.c1, self.c2], calls=1)) is None           # optimize 2회 미만
        assert direct.ask_trigger(self.ds([self.c1])) is None                             # 후보 하나
        same = cand("c3", self.c1.course)
        assert direct.ask_trigger(self.ds([self.c1, same])) is None                       # met 벡터가 같다
        done = direct.Question("q1", "pick_course", None, ("c1", "c2"), "t", "c1")
        assert direct.ask_trigger(self.ds([self.c1, self.c2], questions=[done])) is None  # 이미 물었다

    def test_all_goals_met_means_no_question(self):
        both = cand("c1", (("p6",), ("p1", "p2", "p3"), ("p4", "p5")))
        assert [r.met for r in G.evaluate_all(self.st.trip, both.course, self.goals)] == [True, True]
        assert direct.ask_trigger(self.ds([both, self.c2])) is None

    def test_pair_starts_with_best_candidate_as_default(self):
        pair = direct.ask_trigger(self.ds([self.c1, self.c2]))
        assert pair[0] == direct.best_candidate(self.st, (self.c1, self.c2)).candidate_id and set(pair) == {"c1", "c2"}

    def test_code_opens_the_question_when_model_finishes_and_default_wins(self, monkeypatch):
        cands = (self.c1, self.c2)
        monkeypatch.setattr(direct.opt, "optimize", lambda st, **kw: (st, cands))
        other = "c2" if direct.best_candidate(self.st, cands).candidate_id == "c1" else "c1"
        decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "optimize", "priority": [], "locks": []},
                          {"tool": "finish", "candidate_id": other}, {"tool": "finish", "candidate_id": other})
        result = direct.run_direct(self.st, decide=decide, hours=TRUE_HOURS)
        asked = [s for s in acts(result) if s.call["tool"] == "ask_requester"]
        assert len(asked) == 1 and asked[0].by == "code" and asked[0].substituted_for["error"] == "QUESTION_OPENED_BY_CODE"
        assert len(result.questions) == 1 and result.questions[0].kind == "pick_course"
        assert result.chosen.candidate_id == result.questions[0].default                  # 답이 없으니 기본 선택지로 이어 간다
        assert acts(result)[-1].result.data["note"]

    def test_must_ask_is_in_model_input_only_when_condition_holds(self):
        on = direct.direct_input(self.ds([self.c1, self.c2]), None, 3, 0)["must_ask"]
        assert on["kind"] == "pick_course" and len(on["candidates"]) == 2
        assert direct.direct_input(self.ds([self.c1, self.c2], calls=1), None, 3, 0)["must_ask"] is None

    def test_turns_running_out_also_opens_the_question(self, monkeypatch):
        cands = (self.c1, self.c2)
        monkeypatch.setattr(direct.opt, "optimize", lambda st, **kw: (st, cands))
        opt = {"tool": "optimize", "priority": [], "locks": []}
        result = direct.run_direct(self.st, decide=scripted(*([opt] * 5)), hours=TRUE_HOURS)
        assert len(result.questions) == 1 and result.chosen.candidate_id == result.questions[0].default


class TestCheckGoals:
    def labeled(self, specs, days=(MON, TUE), hours=None):
        tr = trip(places=tuple(place(a, c, 37.5665, 126.978, lab) for a, c, lab in specs), days=days)
        return tr, hours or {}

    def check(self, tr, hours, goal):
        return G.check_goal(tr, hours, goal)

    def test_night_end_codes(self):
        tr, h = self.labeled([("p1", "관광지", ("night_view",)), ("p2", "카페", ("quiet",))])
        ok = self.check(tr, {**h, "p1": ALL_OPEN}, Goal("night_end", "d1"))
        assert ok["feasible"] is True and ok["facts"]["night_places"] == 1 and ok["facts"]["labeled_places"] == 2
        none = self.check(*self.labeled([("p1", "관광지", ("quiet",))]), Goal("night_end", "d1"))
        assert none["feasible"] is False and none["reasons"] == [G.NO_NIGHT_PLACE]
        closed = {"p1": {MON.weekday(): "closed", TUE.weekday(): "open"}}
        res = self.check(tr, closed, Goal("night_end", "d1"))
        assert res["feasible"] is False and res["reasons"] == [G.NIGHT_PLACE_CLOSED_ON_DAY]
        assert res["facts"]["night_closed_days"] == {"p1": ["d1"]}
        assert self.check(tr, closed, Goal("night_end", "d2"))["feasible"] is True               # 둘째 날은 연다
        unknown = self.check(*self.labeled([("p1", "관광지", ())]), Goal("night_end", "d1"))
        assert unknown["feasible"] is None and unknown["reasons"] == [G.LABELS_UNKNOWN]

    def test_day_indoor_few_indoor(self):
        tr, h = self.labeled([("p1", "관광지", ("is_indoor",)), ("p2", "관광지", ("quiet",)), ("p3", "관광지", ("quiet",)),
                              ("p4", "관광지", ("quiet",))])
        res = self.check(tr, h, Goal("day_indoor", "d1"))                  # 하루 평균 2곳 → 실내 2곳 필요, 1곳뿐
        assert res["feasible"] is False and res["reasons"] == [G.FEW_INDOOR] and res["facts"]["needed"] == 2
        tr2, h2 = self.labeled([(f"p{i}", "관광지", ("is_indoor",)) for i in range(1, 5)])
        assert self.check(tr2, h2, Goal("day_indoor", "d1"))["feasible"] is True
        closed = {p: {MON.weekday(): "closed"} for p in ("p1", "p2", "p3")}                 # 실내가 그날 쉬면 세지 않는다 — 1곳만 남아 필요 2곳에 못 미친다
        assert self.check(tr2, closed, Goal("day_indoor", "d1"))["feasible"] is False

    def test_place_on_day_and_together(self):
        tr, _ = self.labeled([("p1", "관광지", ()), ("p2", "관광지", ())])
        h = {"p1": {MON.weekday(): "closed"}, "p2": {TUE.weekday(): "closed"}}
        res = self.check(tr, h, Goal("place_on_day", "d1", ("p1",)))
        assert res["feasible"] is False and res["reasons"] == [G.PLACE_CLOSED_ON_DAY] and res["facts"]["place_closed_days"] == ["d1"]
        assert self.check(tr, h, Goal("place_on_day", "d2", ("p1",)))["feasible"] is None       # 그날 영업 여부를 모른다
        assert self.check(tr, {**h, "p1": ALL_OPEN}, Goal("place_on_day", "d2", ("p1",)))["feasible"] is True
        res = self.check(tr, h, Goal("together", None, ("p1", "p2")))                          # d1은 p1이, d2는 p2가 쉰다
        assert res["feasible"] is False and res["reasons"] == [G.NO_COMMON_OPEN_DAY]
        assert self.check(tr, {"p1": h["p1"]}, Goal("together", None, ("p1", "p2")))["facts"]["common_open_days"] == ["d2"]

    def test_walk_and_light_are_always_possible_and_sentences_are_templated(self):
        tr, h = self.labeled([("p1", "관광지", ())])
        assert self.check(tr, h, Goal("daily_walk_low"))["feasible"] is True
        none = self.check(*self.labeled([("p1", "관광지", ("quiet",))]), Goal("night_end", "d1"))
        assert G.check_sentence(tr, none, Goal("night_end", "d1")).endswith("야경 명소가 이 리스트에 없어요")

    def test_day_has_without_and_with_a_tagged_place(self):
        goal = Goal("day_has", "d2", (), "performance")
        tr, h = self.labeled([("p1", "관광지", ("quiet",)), ("p2", "카페", ("quiet",))])
        none = self.check(tr, h, goal)
        assert none["feasible"] is False and none["reasons"] == [G.NO_TAGGED_PLACE] and none["facts"]["tagged_places"] == 0
        assert G.check_sentence(tr, none, goal) == "둘째 날 (화)에 공연 장소 넣기: 확정 리스트에 공연 장소가 없어요"
        tr2, _ = self.labeled([("p1", "관광지", ("performance",)), ("p2", "카페", ("quiet",))])
        assert self.check(tr2, {"p1": ALL_OPEN}, goal)["feasible"] is True
        closed = {"p1": {TUE.weekday(): "closed"}}
        res = self.check(tr2, closed, goal)
        assert res["feasible"] is False and res["reasons"] == [G.TAGGED_PLACE_CLOSED_ON_DAY]
        assert G.check_sentence(tr2, res, goal).endswith("공연 장소가 그날 모두 쉬어요")
        unknown = self.check(*self.labeled([("p1", "관광지", ())]), goal)
        assert unknown["feasible"] is None and unknown["reasons"] == [G.LABELS_UNKNOWN]

    def test_loop_runs_check_first_and_puts_it_in_model_input(self):
        decide = scripted({"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(state([NIGHT_D1]), decide=decide, hours=TRUE_HOURS)
        assert result.steps[0].by == "code" and result.steps[0].call == {"tool": "check_goals"} and result.checks[0]["id"] == NIGHT_D1.id
        assert decide.seen[0]["goal_checks"] == list(result.checks)


class TestWorklog:
    def test_stages_in_order_with_who(self, monkeypatch):
        from agent.course import worklog
        cands = (cand("c1", (("p1", "p2", "p6"), ("p3", "p4"), ("p5",))), cand("c2", (("p5",), ("p1", "p2", "p3"), ("p4", "p6"))))
        goals = [NIGHT_D1, Goal("day_light", "d1")]
        st = state(goals)
        monkeypatch.setattr(direct.opt, "optimize", lambda s, **kw: (s, cands))
        opt = {"tool": "optimize", "priority": [], "locks": []}
        decide = scripted(opt, opt, {"tool": "finish", "candidate_id": "c1"}, {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(st, decide=decide, hours=TRUE_HOURS)
        lines = worklog.render(st.trip, goals, ["웨이팅 없는 곳"], result)
        stages = [l.split("]")[0][1:] for l in lines]
        assert stages[0] == "이해" and "확인" in stages and stages.index("확인") < stages.index("짜기")
        assert "재계획" in stages and "질문" in stages and stages[-2:] == ["끝", "결과"]
        assert lines[0].startswith("[이해] 해석(모델)") and "「웨이팅 없는 곳」은 그대로는 판단할 수 없어요" in lines[0]
        ask = next(l for l in lines if l.startswith("[질문]"))
        assert "코드가 열음" in ask and "A: " in ask and "기본값" in ask
        assert all("(" in l and ")" in l for l in lines)                            # 단계마다 누가
