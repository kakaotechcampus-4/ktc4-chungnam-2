"""이동 위반이 남았을 때 코드가 여는 질문(split_day) — 막힌 곳(이동)을 겨눈다. 영업 여부 질문은 이동 위반이 있는 동안 열지 않는다."""

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

    def test_not_asked_twice_for_the_same_day(self):
        s = make_state()
        ds = ds_with(s)
        ds2, _ = direct.execute(direct._split_call(direct.pending_split(ds)), ds, O_GATEWAY, "code")
        again = direct.DirectState(ds2.state, candidates=(stuck_candidate(ds2.state, STUCK),), questions=ds2.questions)
        assert direct.pending_split(again) is None


class _Gateway:
    def get_opening_hours(self, place_ids):
        return {pid: None for pid in place_ids}            # 조회해도 모른다


O_GATEWAY = _Gateway()


class TestQuestion:
    def test_default_applies_the_first_option_and_locks_what_moved(self):
        s = make_state()
        ds = ds_with(s)
        split = direct.pending_split(ds)
        first = split["options"][0]
        ds2, result = direct.execute(direct._split_call(split), ds, O_GATEWAY, "code")
        q = ds2.questions[0]
        assert result.ok and q.kind == "split_day" and q.subject == "d1" and q.default == "m1"
        assert q.options[-1] == direct.KEEP and q.option_labels[-1] == "그대로 두기" and len(q.option_labels) == len(q.options)
        assert q.text.endswith("다른 날로 나눌까요?") and "같은 날 넣었어요" in q.text and "대중교통 약" in q.text
        assert ds2.state.course == first.course and ds2.candidates == ()
        assert all(ds2.state.locks[p] == first.to_day for p in first.places)
        assert core.hard_score(ds2.state.violations)[0] == 0

    def test_model_may_only_pick_among_code_options_and_the_first_is_the_default(self):
        s = make_state()
        ds = ds_with(s)
        ids = [o.option_id for o in direct.pending_split(ds)["options"]]
        assert len(ids) >= 2
        picked = direct.execute(direct.CourseAskRequester(tool="ask_requester", kind="split_day", subject="d1", options=[ids[1], ids[0]]), ds, O_GATEWAY)
        assert picked[1].ok and picked[0].questions[0].default == ids[1]
        for bad in (["m9"], [], [ids[0], ids[0]]):
            r = direct.execute(direct.CourseAskRequester(tool="ask_requester", kind="split_day", subject="d1", options=bad), ds, O_GATEWAY)[1]
            assert not r.ok and r.error == "INVALID_MOVE"
        wrong_day = direct.execute(direct.CourseAskRequester(tool="ask_requester", kind="split_day", subject="d2", options=[ids[0]]), ds, O_GATEWAY)[1]
        assert wrong_day.error == "INVALID_ID"

    def test_must_ask_shows_the_model_alias_options_only(self):
        s = make_state()
        must = direct.direct_input(ds_with(s), None, 2, 0)["must_ask"]
        assert must["kind"] == "split_day" and must["subject"] == "d1"
        assert all(set(o) == {"id", "places", "to_day"} and o["places"][0].startswith("p") for o in must["options"])

    def test_asking_opening_hours_is_refused_while_a_travel_violation_remains(self):
        hours = {**OPEN, "p1": {}}                                   # p1의 영업 여부를 모른다 — 평소엔 물을 수 있다
        s = make_state(hours=hours)
        ask = direct.CourseAskRequester(tool="ask_requester", kind="ask_closed_day", subject="p1")
        r = direct.execute(ask, ds_with(s), O_GATEWAY)[1]
        assert not r.ok and r.error == "BLOCKED_BY_TRAVEL"
        fine = (("p1", "p2"), ("p3", "p4"), ())
        assert direct.execute(ask, ds_with(s, fine), O_GATEWAY)[1].ok

    def test_opening_hours_question_is_also_refused_when_no_split_exists(self):
        one = (("p1", "p2", "p3", "p4"),)
        s = make_state(one, days=(MON,), hours={**OPEN, "p1": {}})        # 하루뿐 — 나눌 길이 없다
        ds = ds_with(s, one)
        assert direct.pending_split(ds) is None
        ask = direct.CourseAskRequester(tool="ask_requester", kind="ask_closed_day", subject="p1")
        assert direct.execute(ask, ds, O_GATEWAY)[1].error == "BLOCKED_BY_TRAVEL"


class TestLoop:
    def test_model_asking_opening_hours_is_replaced_by_the_travel_question(self, monkeypatch):
        stub_optimize(monkeypatch)
        s = make_state(hours={**OPEN, "p1": {}}, goals=WALK_LOW)
        decide = scripted({"tool": "optimize", "priority": [], "locks": []},
                          {"tool": "ask_requester", "kind": "ask_closed_day", "subject": "p1"},
                          {"tool": "optimize", "priority": [], "locks": []},
                          {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(s, decide=decide, hours=O_GATEWAY)
        kinds = [q.kind for q in result.questions]
        assert kinds == ["split_day"]                                  # 영업 여부 질문은 열리지 않았다
        sub = next(st for st in result.steps if st.substituted_for)
        assert sub.substituted_for["call"]["kind"] == "ask_closed_day" and sub.by == "code"
        assert result.outcome in ("solved", "solved_with_checks") and core.hard_score(result.violations)[0] == 0

    def test_a_wrong_model_split_question_is_opened_by_code_instead(self, monkeypatch):
        stub_optimize(monkeypatch)
        s = make_state(goals=WALK_LOW)
        decide = scripted({"tool": "optimize", "priority": [], "locks": []},
                          {"tool": "ask_requester", "kind": "split_day", "subject": "d1", "options": ["m9"]},
                          {"tool": "optimize", "priority": [], "locks": []},
                          {"tool": "finish", "candidate_id": "c1"})
        result = direct.run_direct(s, decide=decide, hours=O_GATEWAY)
        assert [q.kind for q in result.questions] == ["split_day"] and result.questions[0].default == "m1"

    def test_without_a_model_the_code_asks_and_then_rebuilds(self, monkeypatch):
        stub_optimize(monkeypatch)
        result = direct.run_direct(make_state(), decide=None, hours=O_GATEWAY)
        assert [q.kind for q in result.questions] == ["split_day"]
        assert core.hard_score(result.violations)[0] == 0
        assert [s.call["tool"] for s in result.steps if s.turn > 0][:3] == ["optimize", "ask_requester", "optimize"]

    def test_no_question_when_the_course_has_no_travel_violation(self):
        s = make_state((("p1", "p2"), ("p3", "p4"), ()))
        result = direct.run_direct(s, decide=None, hours=O_GATEWAY)
        assert result.questions == ()


class TestWorklog:
    def test_the_question_and_default_answer_are_recorded(self, monkeypatch):
        stub_optimize(monkeypatch)
        s = make_state()
        result = direct.run_direct(s, decide=None, hours=O_GATEWAY)
        lines = worklog.render(s.trip, (), (), result)
        q = next(line for line in lines if line.startswith("[질문]"))
        assert "코드가 열음 → 사람" in q and "다른 날로 나눌까요?" in q and "그대로 두기" in q and "기본값" in q
        assert any(line.startswith("[답]") and "이어 가요" in line for line in lines)
        assert any(line.startswith("[다시 짜기]") for line in lines)
