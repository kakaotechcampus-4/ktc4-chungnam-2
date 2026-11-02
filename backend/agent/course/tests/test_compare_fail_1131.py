"""#1131 C안(후보를 견줘 정하고 그 이유를 남긴다)과 D안(모델이 실패해 코드가 이어받은 단계를 남긴다)."""

import re
from types import SimpleNamespace

from agent.course import direct, optimize as O, worklog
from agent.course.gateways import NullOpeningHours
from agent.course.goals import Goal
from agent.course.runner import run_course
from agent.course.tests.fixtures import TRUE_HOURS
from agent.course.tests.test_optimize_direct import NIGHT_D1, scripted, state
from agent.course.tests.test_runner import TEXT, build, goals_planner
from llm.client import LlmCallError

P1_D3 = Goal("place_on_day", "d3", ("p1",))          # 기준선은 p1을 첫날에 두므로 목표 후보와 균형 후보의 코스가 갈린다


def lines(st, goals, result, **kw):
    return worklog.render(st.trip, goals, [], result, **kw)


class TestCandidates:
    def test_one_goal_gets_a_balanced_candidate_with_another_course(self):
        _, cands = O.optimize(state([P1_D3]), priority=[], gateway=TRUE_HOURS)
        assert [c.balanced for c in cands] == [False, True] and cands[0].course != cands[1].course

    def test_same_course_is_not_made_twice(self):
        _, cands = O.optimize(state([NIGHT_D1]), priority=[], gateway=TRUE_HOURS)
        assert len(cands) == 1 and not cands[0].balanced                      # 균형 후보가 목표 후보와 같은 코스다 — 지어내지 않는다

    def test_no_goals_no_balanced_candidate(self):
        _, cands = O.optimize(state(), priority=[], gateway=TRUE_HOURS)
        assert len(cands) == 1 and not cands[0].balanced


class TestCompareLines:
    def test_rows_and_decision_reason_before_the_end(self):
        st = state([P1_D3])
        result = direct.run_direct(st, decide=None, hours=TRUE_HOURS)
        out = lines(st, [P1_D3], result)
        stages = [l.split("]")[0][1:] for l in out]
        i = stages.index("끝")
        assert stages[i - 2:i] == ["비교", "비교"]
        assert out[i - 2].startswith("[비교] 검증(코드) 1번 안(요청 목표를 최대한): 목표 1개 중 1개 지킴, 확정 위반 0개")
        assert "2번 안(요청 목표 없이 이동과 날짜 균형 먼저): 목표 1개 중 0개 지킴" in out[i - 1]
        assert out[i] == "[끝] 지휘(코드) 2번 안은 ‘장소P1이름을 셋째 날 (수)에’ 목표를 못 지켜서 1번 안으로 정했어요."

    def test_one_course_says_no_other_shape_was_found(self):
        st = state([NIGHT_D1])
        result = direct.run_direct(st, decide=None, hours=TRUE_HOURS)
        out = lines(st, [NIGHT_D1], result)
        compare = [l for l in out if l.startswith("[비교]")]
        assert compare == ["[비교] 검증(코드) 다른 짜임을 찾지 못했어요. 이 장소들로는 코스가 하나로 모여요."]
        assert any(l == "[끝] 지휘(코드) 1번 안으로 정했어요." for l in out)

    def test_no_goals_no_compare(self):
        st = state()
        result = direct.run_direct(st, decide=None, hours=TRUE_HOURS)
        assert not any(l.startswith("[비교]") for l in lines(st, [], result)) and result.model_turns == 0

    def test_decision_text_names_what_was_gained_and_lost(self):
        st = state([NIGHT_D1, Goal("day_light", "d1")])
        by_id = {g.id: g for g in st.goals}
        row = lambda cid, kept, walk, transit=0, confirmed=0: {"candidate_id": cid, "kept": kept, "total": 2, "confirmed": confirmed,
                                                               "walk_day_max": walk, "transit_legs": transit, "focus": None, "balanced": False}
        data = {"candidate_id": "c1", "code_best": "c1", "distinct": 3, "compare": [
            row("c1", [NIGHT_D1.id], 30), row("c2", ["day_light:d1"], 10), row("c3", [NIGHT_D1.id], 40, confirmed=1)]}
        text = worklog.decision_text(st.trip, by_id, data)
        assert text == ("2번 안은 ‘첫째 날 (월)은 여유 있게’ 목표는 지키지만 ‘첫째 날 (월) 마지막은 야경 명소’ 목표를 못 지켜서, "
                        "3번 안은 확정 위반이 더 남아서 1번 안으로 정했어요.")
        data["compare"][1] = row("c2", [NIGHT_D1.id], 30)
        data["compare"] = data["compare"][:2]
        assert "영업 확인, 목표 순서, 날짜 균형까지 견주면 덜 맞아서" in worklog.decision_text(st.trip, by_id, data)
        data["code_best"] = "c2"
        assert "모델의 판단으로 1번 안으로" in worklog.decision_text(st.trip, by_id, data)

    def test_code_made_compare_lines_have_no_latin_or_dots(self):
        st = state([P1_D3])
        result = direct.run_direct(st, decide=None, hours=TRUE_HOURS)
        for r in worklog.records(st.trip, [P1_D3], [], result):
            if r.stage in ("비교", "끝"):
                bare = re.sub(r"장소P\d이름", "", r.text)
                assert not re.search(r"[A-Za-z]", bare) and "·" not in bare, r.text


class _Failed(RuntimeError):
    def __init__(self, reason):
        super().__init__("x")
        self.failure = SimpleNamespace(reason=reason)


class TestFailures:
    def test_failure_kinds(self):
        assert direct.failure_kind(_Failed("timeout")) == direct.TIMEOUT
        assert direct.failure_kind(_Failed("invalid_schema")) == direct.BAD_FORMAT
        assert direct.failure_kind(_Failed("call_failed")) == direct.NO_RESPONSE
        assert direct.failure_kind(TimeoutError()) == direct.TIMEOUT

    def test_one_direct_turn_fails_and_code_takes_over_with_a_line(self):
        st = state([P1_D3])
        good = scripted({"tool": "optimize", "priority": [], "locks": []})
        calls = []

        def decide(turn_input):
            calls.append(1)
            if len(calls) == 2:
                raise _Failed("timeout")
            return good(turn_input)

        result = direct.run_direct(st, decide=decide, hours=TRUE_HOURS)
        out = lines(st, [P1_D3], result)
        taken = [l for l in out if l.startswith("[대행]")]
        assert taken == ["[대행] 지휘(코드) 모델 응답이 시간 안에 오지 않아 이번 단계는 코드가 이어서 골랐어요."]
        assert result.outcome in ("solved", "solved_with_checks") and out[-1].startswith("[결과]")
        step = next(s for s in result.steps if s.substituted_for)
        assert step.substituted_for == {"call": None, "error": direct.MODEL_FAILED, "failure": direct.TIMEOUT}

    def test_every_direct_turn_fails_and_the_result_still_comes(self):
        st = state([P1_D3])

        def decide(_input):
            raise _Failed("invalid_schema")

        result = direct.run_direct(st, decide=decide, hours=TRUE_HOURS)
        out = lines(st, [P1_D3], result)
        taken = [l for l in out if l.startswith("[대행]")]
        assert taken == ["[대행] 지휘(코드) 모델 응답의 형식이 맞지 않아 이번 단계는 코드가 이어서 짰어요.",
                         "[대행] 지휘(코드) 모델 응답의 형식이 맞지 않아 이번 단계는 코드가 이어서 골랐어요."]
        assert result.model_turns == 0 and result.chosen is not None and any(l.startswith("[비교]") for l in out)
        assert all("invalid_schema" not in l and "Error" not in l for l in out)

    def test_goal_setting_failure_leaves_a_line_and_the_course_still_comes(self):
        def failing(_input):
            raise LlmCallError("timeout", reason="timeout")

        out = run_course(build(), TEXT, goals_planner=failing, direct_planner=None, gateway=NullOpeningHours())
        steps = out.view.steps
        assert steps[1]["stage"] == "대행" and steps[1]["by"] == "code"
        assert steps[1]["text"] == "모델 응답이 시간 안에 오지 않아 목표를 세우지 못했어요. 요청 목표 없이 기본 기준으로 짜요."
        assert steps[-1]["stage"] == "결과" and out.view.outcome == "solved_with_checks"

    def test_success_has_no_takeover_line(self):
        out = run_course(build(), TEXT, goals_planner=goals_planner, direct_planner=None, gateway=NullOpeningHours())
        assert not any(s["stage"] == "대행" for s in out.view.steps)


class TestSameCourse:
    """#1140 검수: 고른 안과 코스가 같은 후보는 비교 줄에 한 번만 나오고, 결정 이유에 그 후보 절이 없다."""

    def run_with(self, monkeypatch, cands, finish):
        st = state([P1_D3])
        monkeypatch.setattr(direct.opt, "optimize", lambda s, **kw: (s, cands))
        result = direct.run_direct(st, decide=scripted({"tool": "optimize", "priority": [], "locks": []},
                                                       {"tool": "finish", "candidate_id": finish}), hours=TRUE_HOURS)
        return st, result, lines(st, [P1_D3], result)

    def test_a_duplicate_of_the_chosen_course_is_shown_once(self, monkeypatch):
        _, real = O.optimize(state([P1_D3]), priority=[], gateway=TRUE_HOURS)
        goal_course, balanced_course = real[0].course, real[1].course
        cands = (O.Candidate("c1", goal_course, (), ()), O.Candidate("c2", balanced_course, (), (), balanced=True),
                 O.Candidate("c3", goal_course, (), ()))
        _, result, out = self.run_with(monkeypatch, cands, "c3")
        data = next(s for s in result.steps if s.call.get("tool") == "finish").result.data
        assert [r["candidate_id"] for r in data["compare"]] == ["c2", "c3"] and data["distinct"] == 2 and data["code_best"] == "c3"
        compare = [l for l in out if l.startswith("[비교]")]
        assert len(compare) == 2 and not any("1번 안" in l for l in compare)
        end = next(l for l in out if l.startswith("[끝]"))
        assert "1번 안" not in end and end.endswith("2번 안은 ‘장소P1이름을 셋째 날 (수)에’ 목표를 못 지켜서 3번 안으로 정했어요.")

    def test_all_the_same_course_is_the_no_other_shape_line(self, monkeypatch):
        course = O.optimize(state([P1_D3]), priority=[], gateway=TRUE_HOURS)[1][0].course
        cands = (O.Candidate("c1", course, (), ()), O.Candidate("c2", course, (), ()))
        _, _, out = self.run_with(monkeypatch, cands, "c2")
        assert [l for l in out if l.startswith("[비교]")] == ["[비교] 검증(코드) 다른 짜임을 찾지 못했어요. 이 장소들로는 코스가 하나로 모여요."]
        assert any(l.startswith("[끝]") and l.endswith("2번 안으로 정했어요.") for l in out)
