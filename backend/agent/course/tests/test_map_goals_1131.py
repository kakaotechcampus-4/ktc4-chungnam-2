"""#1131 B안: 지도 근거(우리 조건 요약·장소 라벨)로 목표 후보를 모으고, 목표 세우기가 그중에서만 골라 「지도에서 세운 목표」로 지킨다."""

from types import SimpleNamespace

from agent.course import direct, goals as G, service, worklog
from agent.course.constants import GOALS_MAX, MAP_GOAL_KEYS
from agent.course.gateways import NullOpeningHours
from agent.course.goals import Goal, SummaryItem
from agent.course.runner import run_course
from agent.course.state import initial_state
from agent.course.tests.fixtures import ALL_OPEN, PLACES, trip
from agent.course.tests.test_runner import build
from llm.schemas import CourseDirectTurn, CourseGoal, CourseGoalSet

WALK = SummaryItem("관광지", "accessible", True, 2, "휠체어·유모차")
INDOOR = SummaryItem("관광지", "is_indoor", True, 3, "실내")
OTHER = SummaryItem("음식점", "spicy", False, 4, "매운맛 전문")


def _goal(kind, source="request", candidate_id=None, day=None, quote=""):
    return SimpleNamespace(kind=kind, day=day, places=[], tag=None, quote=quote, source=source, candidate_id=candidate_id)


def _verify(text, goals, candidates):
    return G.verify_goal_set(trip(), text, SimpleNamespace(goals=goals, unmatched=[]), candidates)


class TestCandidates:
    def test_table_decides_kind_and_unrelated_keys_are_ignored(self):
        cands = G.map_candidates(trip(), [OTHER, INDOOR, WALK, SummaryItem("관광지", "walkable", False, 1, "산책")])
        assert [(c.id, c.kind) for c in cands] == [("g1", "daily_walk_low"), ("g2", "day_indoor"), ("g3", "night_end")]
        assert [i.fact_key for i in cands[0].items] == ["accessible", "walkable"]          # 사람 수가 많은 순
        assert cands[2].items == () and cands[2].night_places == ("p6",)                  # 확정 장소의 야경 라벨만으로도 후보
        assert all(MAP_GOAL_KEYS[(i.fact_key, i.wants)] == c.kind for c in cands for i in c.items)

    def test_no_evidence_no_candidates(self):
        no_night = tuple(p for p in PLACES if p.alias != "p6")
        assert G.map_candidates(trip(places=no_night, days=trip().days[:2]), [OTHER]) == ()

    def test_evidence_text_has_key_names_and_counts_only(self):
        cands = G.map_candidates(trip(), [WALK])
        assert G.evidence_text(cands[0]) == "관광지 조건 요약의 ‘휠체어·유모차 원함’ 2명"
        assert G.evidence_text(cands[1]) == "확정 장소 중 야경 명소 1곳"

    def test_goals_input_has_candidates_without_names(self):
        got = G.goals_input(trip(), "", G.map_candidates(trip(), [WALK]))
        assert got["map_candidates"][0] == {"id": "g1", "kind": "daily_walk_low", "required": False, "night_places": [],
                                            "evidence": [{"category": "관광지", "fact_key": "accessible", "wants": True, "members": 2}]}
        assert "휠체어" not in str(got["map_candidates"])


class TestVerify:
    CANDS = G.map_candidates(trip(), [WALK, INDOOR])

    def test_map_goal_from_a_candidate_is_kept_with_origin(self):
        v = _verify("", [_goal("daily_walk_low", "map", "g1"), _goal("night_end", "map", "g3", day="d2")], self.CANDS)
        assert [(g.id, g.origin, g.candidate) for g in v.goals] == [("daily_walk_low", "map", "g1"), ("night_end:d2", "map", "g3")]

    def test_goal_outside_candidates_or_with_another_kind_is_dropped(self):
        v = _verify("", [_goal("day_light", "map", "g1", day="d1"), _goal("daily_walk_low", "map", "g9"),
                         _goal("daily_walk_low", "map", None)], self.CANDS)
        assert v.goals == () and len(v.dropped) == 3 and v.unmatched == ()

    def test_one_goal_per_candidate(self):
        v = _verify("", [_goal("day_indoor", "map", "g2", day="d1"), _goal("day_indoor", "map", "g2", day="d2")], self.CANDS)
        assert [g.id for g in v.goals] == ["day_indoor:d1"]

    def test_request_goals_come_first_and_win_the_same_id(self):
        text = "많이 못 걸어요"
        v = _verify(text, [_goal("daily_walk_low", "map", "g1"), _goal("daily_walk_low", quote=text)], self.CANDS)
        assert [(g.id, g.origin) for g in v.goals] == [("daily_walk_low", "request")]

    def test_map_goals_are_cut_first_under_goals_max(self):
        text = "첫날 여유, 둘째 날 여유, 셋째 날 여유"
        asked = [_goal("day_light", day=f"d{i}", quote=q) for i, q in enumerate(text.split(", "), 1)]
        v = _verify(text, [_goal("daily_walk_low", "map", "g1"), _goal("day_indoor", "map", "g2", day="d1"), *asked], self.CANDS)
        assert len(v.goals) == GOALS_MAX and [g.origin for g in v.goals] == ["request"] * 3 + ["map"]

    def test_label_marks_map_goals(self):
        g = Goal("daily_walk_low", origin="map", candidate="g1")
        assert G.label(trip(), g) == "하루 걷는 시간 줄이기 (지도에서 세운 목표)"
        assert G.label(trip(), g, mark=False) == "하루 걷는 시간 줄이기" and G.retarget(Goal("night_end", "d1", origin="map"), "d2").origin == "map"


class TestOpening:
    CANDS = G.map_candidates(trip(), [WALK])

    def opening(self, goals=(), unmatched=(), cands=CANDS):
        return worklog.Narrator(trip(), goals, unmatched, candidates=cands).opening()[0].text

    def test_empty_request_with_map_goals_states_source_and_evidence(self):
        text = self.opening([Goal("daily_walk_low", origin="map", candidate="g1")])
        assert text == ("이렇게 이해했어요: 요청이 없어서 지도에서 목표를 세웠어요: 하루 걷는 시간 줄이기. "
                        "(근거: 관광지 조건 요약의 ‘휠체어·유모차 원함’ 2명)")

    def test_request_and_map_goals_together(self):
        text = self.opening([Goal("day_light", "d1"), Goal("night_end", "d2", origin="map", candidate="g2")])
        assert text.startswith("이렇게 이해했어요: 첫째 날") and "지도에서도 목표를 세웠어요: 둘째 날" in text and "야경 명소 1곳" in text

    def test_no_goals_sentence_only_when_there_were_no_candidates(self):
        assert self.opening(cands=()) == "이렇게 이해했어요: " + worklog.NO_GOALS_OPENING
        assert self.opening() == "이렇게 이해했어요: " + worklog.MAP_NONE_OPENING


class TestRunner:
    def planner(self, calls):
        def plan(goals_input):
            calls.append(goals_input)
            return CourseGoalSet(goals=[CourseGoal(kind="daily_walk_low", source="map", candidate_id="g1")], unmatched=[])
        return plan

    def test_empty_request_calls_goal_setting_when_candidates_exist(self):
        calls = []
        out = run_course(build(), "", goals_planner=self.planner(calls), direct_planner=None, gateway=NullOpeningHours(), map_items=(WALK,))
        assert len(calls) == 1 and calls[0]["request"] == "" and calls[0]["map_candidates"][0]["kind"] == "daily_walk_low"
        assert [g["label"] for g in out.view.goals] == ["하루 걷는 시간 줄이기 (지도에서 세운 목표)"] and out.view.unmatched == []
        assert out.view.steps[0]["text"].startswith("이렇게 이해했어요: 요청이 없어서 지도에서 목표를 세웠어요")

    def test_no_candidates_no_goal_setting(self):
        calls = []
        out = run_course(build(), "", goals_planner=self.planner(calls), direct_planner=None, gateway=NullOpeningHours())
        assert calls == [] and out.view.goals == []

    def test_delegation_also_uses_candidates(self):
        calls = []
        out = run_course(build(), "알아서 잘 짜줘", goals_planner=self.planner(calls), direct_planner=None, gateway=NullOpeningHours(),
                         map_items=(WALK,))
        assert len(calls) == 1 and out.view.unmatched == [] and out.view.goals[0]["kind"] == "daily_walk_low"


class TestPriority:
    def test_map_goals_go_behind_request_goals_even_if_the_model_puts_them_first(self, monkeypatch):
        asked, mapped = Goal("day_light", "d1"), Goal("daily_walk_low", origin="map", candidate="g1")
        st = initial_state(trip(), {p.alias: ALL_OPEN for p in PLACES}, None, (asked, mapped))
        seen = {}
        real = direct.opt.optimize

        def spy(state, **kw):
            seen["priority"] = list(kw["priority"])
            return real(state, **kw)

        monkeypatch.setattr(direct.opt, "optimize", spy)
        call = CourseDirectTurn.model_validate({"thought": "x", "action": {"tool": "optimize", "priority": [mapped.id, asked.id], "locks": []}}).action
        direct.execute(call, direct.DirectState(st), NullOpeningHours())
        assert seen["priority"] == [asked.id, mapped.id]

    def test_model_input_shows_the_source(self):
        st = initial_state(trip(), {p.alias: ALL_OPEN for p in PLACES}, None, (Goal("daily_walk_low", origin="map", candidate="g1"),))
        assert direct.direct_input(direct.DirectState(st), None, 1, 0)["goals"][0]["source"] == "map"


class TestReadMapItems:
    def test_reads_keys_directions_and_counts_from_summaries(self, monkeypatch):
        rows = [SimpleNamespace(category="관광지", summary={
            "must_keep": [{"fact_key": "accessible", "wants": True, "member_count": 2, "reaction_ids": ["r1", "r2"]}],
            "common_prefs": [{"fact_key": "is_indoor", "wants": True, "member_count": 3, "reaction_ids": ["r3"]}],
            "split_prefs": [{"fact_key": "night_view", "want_count": 2, "avoid_count": 1}],
            "vague_fixable": {"count": 1}, "not_filtered": {"count": 1, "notices": ["allergy"]},
        })]
        monkeypatch.setattr(service.agent_service, "list_summaries", lambda db, map_id: rows)
        monkeypatch.setattr(service.recommend_api, "fact_labels", lambda: {"accessible": "휠체어·유모차", "is_indoor": "실내"})
        assert service.read_map_items(None, "m") == (
            SummaryItem("관광지", "accessible", True, 2, "휠체어·유모차", must_keep=True), SummaryItem("관광지", "is_indoor", True, 3, "실내"))


class TestRequired:
    """스테이징(11-03): 요약 must_keep의 「휠체어·유모차 원함」이 있는데 모델이 야경 후보만 골라 걷기 목표가 서지 않았다."""
    MUST = SummaryItem("관광지", "accessible", True, 2, "휠체어·유모차", must_keep=True)
    PREF_INDOOR = SummaryItem("관광지", "is_indoor", True, 3, "실내")
    MUST_INDOOR = SummaryItem("관광지", "is_indoor", True, 2, "실내", must_keep=True)

    def test_required_only_when_a_line_came_from_must_keep(self):
        cands = G.map_candidates(trip(), [self.MUST, WALK, self.PREF_INDOOR])
        assert [(c.kind, c.required) for c in cands] == [("daily_walk_low", True), ("day_indoor", False), ("night_end", False)]
        assert G.goals_input(trip(), "", cands)["map_candidates"][0]["required"] is True

    def test_required_walk_goal_is_set_even_if_the_model_picks_nothing(self):
        v = _verify("", [], G.map_candidates(trip(), [self.MUST]))
        assert [(g.id, g.origin, g.candidate) for g in v.goals] == [("daily_walk_low", "map", "g1")]

    def test_required_goal_is_set_when_the_model_picked_only_night(self):
        cands = G.map_candidates(trip(), [self.MUST])
        v = _verify("", [_goal("night_end", "map", "g2", day="d3")], cands)
        assert [g.id for g in v.goals] == ["daily_walk_low", "night_end:d3"]                     # 필수 지도 목표가 다른 지도 목표 앞

    def test_preference_candidate_is_not_set_unless_the_model_picks_it(self):
        v = _verify("", [], G.map_candidates(trip(), [WALK, self.PREF_INDOOR]))
        assert v.goals == ()

    def test_required_day_kind_is_not_invented(self):
        v = _verify("", [], G.map_candidates(trip(), [self.MUST_INDOOR]))
        assert v.goals == () and any("필수 지도 후보 g1" in d for d in v.dropped)

    def test_request_goal_with_the_same_id_wins_and_required_outlasts_other_map_goals(self):
        text = "많이 못 걸어요"
        cands = G.map_candidates(trip(), [self.MUST])
        v = _verify(text, [_goal("daily_walk_low", quote=text)], cands)
        assert [(g.id, g.origin) for g in v.goals] == [("daily_walk_low", "request")]
        asked = "첫날 여유, 둘째 날 여유, 셋째 날 여유"
        three = [_goal("day_light", day=f"d{i}", quote=q) for i, q in enumerate(asked.split(", "), 1)]
        v = _verify(asked, [_goal("night_end", "map", "g2", day="d1"), *three], cands)
        assert len(v.goals) == GOALS_MAX and v.goals[-1].id == "daily_walk_low" and v.goals[-1].origin == "map"

    def test_empty_request_runs_with_the_required_goal(self):
        def nothing(_input):
            return CourseGoalSet(goals=[], unmatched=[])

        out = run_course(build(), "", goals_planner=nothing, direct_planner=None, gateway=NullOpeningHours(), map_items=(self.MUST,))
        assert [(g["kind"], g["label"]) for g in out.view.goals] == [("daily_walk_low", "하루 걷는 시간 줄이기 (지도에서 세운 목표)")]
        assert "(근거: 관광지 조건 요약의 ‘휠체어·유모차 원함’ 2명)" in out.view.steps[0]["text"]
