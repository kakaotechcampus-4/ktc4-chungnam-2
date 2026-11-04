"""이동 위반이 남았을 때 코드가 푸는 나누기(resolve_split, #1131) — 나누기마다 짜 보고 견줘 고른다. 요청자에게 묻지 않는다."""

from datetime import date

from agent.course import core, direct, optimize as O, worklog
from agent.course.core import Trip
from agent.course.goals import Goal
from agent.course.optimize import Candidate
from agent.course.state import initial_state
from agent.course.tests.fixtures import ALL_OPEN, MON, TUE, WED
from agent.course.tests.test_walk_repair import far_line
from llm.schemas import CourseDirectTurn

OPEN = {f"p{i}": ALL_OPEN for i in range(1, 5)}
# 30km 간격 일렬 4곳: 한 날에 셋(p1·p2·p3)이면 대중교통 약 200분 > 하루 이동 180분 — 둘까지만 들어간다
STUCK = (("p1", "p2", "p3"), ("p4",), ())


def make_state(course=STUCK, days=(MON, TUE, WED), hours=None, goals=()):
    return initial_state(Trip(places=far_line(4), days=days), hours or OPEN, course, goals)


WALK_LOW = (Goal("daily_walk_low"),)         # 요청 목표가 하나 있어야 모델이 불린다(목표 0개면 모델 없이 끝난다)


def stuck_candidate(state, course=STUCK):
    return Candidate("c1", course, core.find_violations(state.trip, course, state.hours), ())


def ds_with(state, course=STUCK):
    return direct.DirectState(state, candidates=(stuck_candidate(state, course),))


def stub_optimize(monkeypatch):
    """첫 optimize는 이동 위반이 남은 후보를 낸다(올라가기가 못 푼 경우를 흉내) — 이후는 진짜 optimize."""
    real, calls = O.optimize, []

    def fake(state, **kw):
        calls.append(1)
        if len(calls) == 1:
            return state, (stuck_candidate(state),)
        return real(state, **kw)

    monkeypatch.setattr(direct.opt, "optimize", fake)
    return calls


def scripted(*actions):
    queue = [CourseDirectTurn.model_validate({"thought": "해 볼게요", "action": a}) for a in actions]

    def decide(_input):
        return queue.pop(0)

    return decide


class TestSplitOptions:
    def test_only_moves_that_cut_confirmed_violations_become_options(self):
        s = make_state()
        assert core.hard_score(s.violations)[0] == 1
        options = direct.split_options(s, STUCK, "d1")
        assert options and [o.option_id for o in options] == [f"m{i + 1}" for i in range(len(options))]
        for o in options:
            assert core.hard_score(o.violations)[0] < 1
            assert sorted(p for d in o.course for p in d) == ["p1", "p2", "p3", "p4"]
        assert ("p1", "d2") not in {(o.places[0], o.to_day) for o in options}      # p1을 p4 쪽으로 옮기면 그쪽이 넘친다

    def test_best_option_has_fewest_transit_legs(self):
        s = make_state()
        first = direct.split_options(s, STUCK, "d1")[0]
        assert core.course_transit_legs(s.trip, first.course) == min(
            core.course_transit_legs(s.trip, o.course) for o in direct.split_options(s, STUCK, "d1"))

    def test_locks_remove_options(self):
        s = make_state()
        from dataclasses import replace
        locked = replace(s, locks={p: "d1" for p in ("p1", "p2", "p3")})
        assert direct.split_options(locked, STUCK, "d1") == ()

    def test_pending_only_when_a_travel_violation_remains(self):
        s = make_state()
        assert direct.pending_split(ds_with(s))["day"] == "d1"
        fine = (("p1", "p2"), ("p3", "p4"), ())
        assert direct.pending_split(ds_with(s, fine)) is None
        assert direct.pending_split(direct.DirectState(s)) is None             # 후보가 없다

    def test_not_resolved_twice_for_the_same_day(self):
        s = make_state()
        done = direct.resolve_split(ds_with(s), direct.pending_split(ds_with(s)), O_GATEWAY)
        again = direct.DirectState(done.ds.state, candidates=(stuck_candidate(done.ds.state, STUCK),), resolved=done.ds.resolved)
        assert direct.pending_split(again) is None


class _Gateway:
    def get_opening_hours(self, place_ids):
        return {pid: None for pid in place_ids}            # 조회해도 모른다


O_GATEWAY = _Gateway()


class TestResolve:
    def test_every_option_is_tried_and_the_best_is_locked(self):
        s = make_state()
        ds = ds_with(s)
        split = direct.pending_split(ds)
        done = direct.resolve_split(ds, split, O_GATEWAY)
        data = done.result.data
        assert done.result.tool == direct.RESOLVE_SPLIT and data["day"] == "d1"
        assert [t["option_id"] for t in data["tried"]] == [o.option_id for o in split["options"]]
        chosen = next(o for o in split["options"] if o.option_id == data["chosen"])
        assert data["moved"] == list(chosen.places) and all(done.ds.state.locks[p] == chosen.to_day for p in chosen.places)
        assert done.ds.candidates and core.hard_score(direct.best_candidate(done.ds.state, done.ds.candidates).violations)[0] == 0
        assert min(t["confirmed"] for t in data["tried"]) == next(t for t in data["tried"] if t["option_id"] == data["chosen"])["confirmed"]

    def test_decision_sentence_names_the_moved_places_and_passes_verify(self):
        s = make_state()
        done = direct.resolve_split(ds_with(s), direct.pending_split(ds_with(s)), O_GATEWAY)
        moved = [s.trip.place(p).name for p in done.result.data["moved"]]
        assert done.guard == () and all(n in done.note for n in moved) and "이동이 길어서" in done.note and "{" not in done.note

    def test_model_input_has_no_question_fields(self):
        s = make_state()
        got = direct.direct_input(ds_with(s), None, 2, 0)
        assert "must_ask" not in got and "asked" not in got and "asks_left" not in got["budget"]


class TestLoop:
    def test_code_resolves_before_the_model_turn(self, monkeypatch):
        stub_optimize(monkeypatch)
        s = make_state(hours={**OPEN, "p1": {}}, goals=WALK_LOW)
        seen = []
        queue = [CourseDirectTurn.model_validate({"thought": "해 볼게요", "action": a}) for a in (
            {"tool": "optimize", "priority": [], "locks": []}, {"tool": "finish", "candidate_id": "c1"})]

        def decide(turn_input):
            seen.append(turn_input)
            return queue.pop(0)

        result = direct.run_direct(s, decide=decide, hours=O_GATEWAY)
        assert result.model_turns == 2 and seen[1]["last_result"]["tool"] == direct.RESOLVE_SPLIT
        assert [st.call["tool"] for st in result.steps if st.turn > 0] == ["optimize", direct.RESOLVE_SPLIT, "finish"]
        assert result.outcome in ("solved", "solved_with_checks") and core.hard_score(result.violations)[0] == 0

    def test_without_a_model_the_code_resolves_and_finishes(self, monkeypatch):
        stub_optimize(monkeypatch)
        result = direct.run_direct(make_state(), decide=None, hours=O_GATEWAY)
        assert core.hard_score(result.violations)[0] == 0
        assert [s.call["tool"] for s in result.steps if s.turn > 0] == ["optimize", direct.RESOLVE_SPLIT, "finish"]

    def test_nothing_to_resolve_when_the_course_has_no_travel_violation(self):
        s = make_state((("p1", "p2"), ("p3", "p4"), ()))
        result = direct.run_direct(s, decide=None, hours=O_GATEWAY)
        assert not any(st.call["tool"] == direct.RESOLVE_SPLIT for st in result.steps)


class TestWorklog:
    def test_find_try_compare_decide_are_recorded_without_a_question(self, monkeypatch):
        stub_optimize(monkeypatch)
        s = make_state()
        result = direct.run_direct(s, decide=None, hours=O_GATEWAY)
        lines = worklog.render(s.trip, (), (), result)
        stages = [l.split("]")[0][1:] for l in lines]
        assert "질문" not in stages and "답" not in stages
        i = stages.index("찾기")
        tried = len(next(st for st in result.steps if st.call["tool"] == direct.RESOLVE_SPLIT).result.data["tried"])
        assert stages[i:i + tried + 3] == ["찾기", *["옮겨 보기"] * tried, "비교", "결정"]
        assert "이동 위반이 남았어요" in lines[i] and "가장 나아요" in lines[i + tried + 1]
