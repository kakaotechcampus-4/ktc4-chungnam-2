"""요청 목표 6종 — 매개변수 검증, 점수 경계, 라벨 모름 처리, 강한 기준선 비교에 끼우는 값, 모델 출력 검증."""

from types import SimpleNamespace

import pytest

from agent.course import core, goals as G
from agent.course.constants import DAILY_WALK_LOW_MAX_MIN, GOALS_MAX
from agent.course.goals import Goal
from agent.course.tests.fixtures import MON, TUE, place, trip

IN, OUT = ("is_indoor",), ("quiet",)


def t(*places, days=(MON, TUE)):
    return trip(places=tuple(places), days=days)


def A(alias, labels=(), cat="관광지", lat=37.5665):
    return place(alias, cat, lat, 126.978, labels)


class TestNormalize:
    def test_valid_and_extras_are_dropped(self):
        tr = t(A("p1"), A("p2"))
        assert G.normalize(tr, "daily_walk_low", "d1", ["p1"]) == (Goal("daily_walk_low"), None)
        goal, _ = G.normalize(tr, "place_on_day", "d2", ["p1", "p2"])
        assert goal == Goal("place_on_day", "d2", ("p1",))
        assert G.normalize(tr, "together", "d1", ["p1", "p2"])[0] == Goal("together", None, ("p1", "p2"))

    @pytest.mark.parametrize("kind,day,places", [
        ("night_end", None, []),                 # 날짜 없음
        ("night_end", "d3", []),                 # 기간 밖
        ("day_indoor", "x", []),
        ("place_on_day", "d1", []),              # 장소 없음
        ("place_on_day", "d1", ["p9"]),          # 없는 장소
        ("together", None, ["p1"]),              # 둘 필요
        ("together", None, ["p1", "p1"]),        # 같은 장소
        ("teleport", "d1", []),
    ])
    def test_rejects(self, kind, day, places):
        goal, why = G.normalize(t(A("p1"), A("p2")), kind, day, places)
        assert goal is None and why

    def test_ids_are_stable_and_readable(self):
        assert Goal("night_end", "d1").id == "night_end:d1"
        assert Goal("daily_walk_low").id == "daily_walk_low"
        assert Goal("together", None, ("p1", "p2")).id == "together:p1+p2"
        assert Goal("place_on_day", "d2", ("p4",)).id == "place_on_day:d2:p4"


class TestScores:
    def test_indoor_ratio_boundary_and_unknown_labels_are_left_out(self):
        tr = t(A("p1", IN), A("p2", IN), A("p3", OUT), A("p4"))
        g = Goal("day_indoor", "d1")
        r = G.evaluate(tr, (("p1", "p2", "p3"), ("p4",)), g)
        assert r.met is False and r.value == pytest.approx(2 / 3)            # 0.667 < 0.7
        r = G.evaluate(tr, (("p1", "p2", "p3", "p4"), ()), g)
        assert r.value == pytest.approx(2 / 3)                               # 라벨 모르는 p4는 분모에서 뺀다
        assert G.evaluate(tr, (("p1", "p2"), ("p3", "p4")), g).met is True    # 1.0
        r = G.evaluate(tr, (("p4",), ("p1", "p2", "p3")), g)
        assert r.met is None and r.value is None                              # 라벨을 아는 장소가 없다

    def test_indoor_seven_of_ten_is_met(self):
        places = [A(f"p{i}", IN if i <= 7 else OUT) for i in range(1, 11)]
        r = G.evaluate(t(*places), (tuple(p.alias for p in places), ()), Goal("day_indoor", "d1"))
        assert r.value == pytest.approx(0.7) and r.met is True

    def test_night_end(self):
        tr = t(A("p1", ("night_view",)), A("p2", OUT), A("p3"))
        g = Goal("night_end", "d1")
        assert G.evaluate(tr, (("p2", "p1"), ("p3",)), g).met is True
        r = G.evaluate(tr, (("p1", "p2"), ("p3",)), g)
        assert r.met is False and r.gap == 1.0
        assert G.evaluate(tr, (("p1", "p3"), ("p2",)), g).met is None         # 마지막 장소 라벨을 모른다
        assert G.evaluate(tr, (("p1", "p2", "p3"), ()), Goal("night_end", "d2")).met is None   # 빈 날

    def test_daily_walk_low_boundary(self):
        def course_with(minutes):
            step = minutes * 80 / 111_000
            pa, pb = A("p1", lat=37.5), A("p2", lat=37.5 + step)
            tr = t(pa, pb, days=(MON,))
            assert core.travel_minutes(tr, "p1", "p2") == minutes             # 분 계산이 이 경계를 정확히 짚는지 확인
            return tr, (("p1", "p2"),)

        tr, c = course_with(DAILY_WALK_LOW_MAX_MIN)
        assert G.evaluate(tr, c, Goal("daily_walk_low")).met is True
        tr, c = course_with(DAILY_WALK_LOW_MAX_MIN + 1)
        r = G.evaluate(tr, c, Goal("daily_walk_low"))
        assert r.met is False and 0 < r.gap < 0.05

    def test_day_light_cap(self):
        tr = t(*(A(f"p{i}") for i in range(1, 7)), days=(MON, TUE))        # 6곳 2일 → 하루 2곳까지 여유
        assert G.day_light_cap(tr) == 2
        g = Goal("day_light", "d1")
        assert G.evaluate(tr, (("p1", "p2"), ("p3", "p4", "p5", "p6")), g).met is True
        r = G.evaluate(tr, (("p1", "p2", "p3"), ("p4", "p5", "p6")), g)
        assert r.met is False and r.gap == 0.5

    def test_place_on_day_and_together(self):
        tr = t(A("p1"), A("p2"), A("p3"))
        assert G.evaluate(tr, (("p1",), ("p2", "p3")), Goal("place_on_day", "d2", ("p2",))).met is True
        assert G.evaluate(tr, (("p1", "p2"), ("p3",)), Goal("place_on_day", "d2", ("p2",))).met is False
        assert G.evaluate(tr, (("p1", "p2"), ("p3",)), Goal("together", None, ("p1", "p2"))).met is True
        assert G.evaluate(tr, (("p1",), ("p2", "p3")), Goal("together", None, ("p1", "p2"))).met is False


class TestKeyPart:
    def setup_method(self):
        self.tr = t(A("p1", ("night_view",)), A("p2", OUT), A("p3", OUT), A("p4", OUT))
        self.night, self.together = Goal("night_end", "d1"), Goal("together", None, ("p3", "p4"))

    def test_no_goals_is_empty_so_old_comparison_is_unchanged(self):
        assert G.key_part(self.tr, (("p1", "p2"), ("p3", "p4")), ()) == (0, (), ())

    def test_fewer_unmet_goals_sorts_first(self):
        both = G.key_part(self.tr, (("p2", "p1"), ("p3", "p4")), [self.night, self.together])
        one = G.key_part(self.tr, (("p3", "p2", "p1"), ("p4",)), [self.night, self.together])
        assert both[0] == 0 and one[0] == 1 and both < one

    def test_priority_decides_which_unmet_goal_is_worse(self):
        course = (("p3", "p2", "p1"), ("p4",))                    # 야경 충족, 묶기 미충족
        goals = [self.night, self.together]
        night_first = G.key_part(self.tr, course, goals, [self.night.id, self.together.id])
        together_first = G.key_part(self.tr, course, goals, [self.together.id, self.night.id])
        assert night_first[1] == (False, True) and together_first[1] == (True, False)
        assert night_first < together_first                        # 야경을 더 중요하게 두면 이 코스가 낫다

    def test_unknown_counts_as_unmet_so_it_cannot_be_gamed(self):
        known = G.key_part(self.tr, (("p2", "p1"), ("p3", "p4")), [self.night])
        assert known[0] == 0
        empty_day = G.key_part(t(A("p1", ("night_view",))), (("p1",), ()), [Goal("night_end", "d2")])
        assert empty_day[0] == 1                                   # 판단할 수 없는 목표도 못 이룬 것으로 센다


class TestVerifyGoalSet:
    TEXT = "마지막 날 밤엔 야경 보고 싶어요, 웨이팅 없는 곳으로"

    def setup_method(self):
        self.tr = t(A("p1", ("night_view",)), A("p2"))

    def goal(self, **kw):
        base = dict(kind="night_end", day="d2", places=[], source="request", quote="마지막 날 밤엔 야경 보고 싶어요", reaction_ids=[])
        return SimpleNamespace(**{**base, **kw})

    def verify(self, goals, unmatched=()):
        return G.verify_goal_set(self.tr, self.TEXT, SimpleNamespace(goals=goals, unmatched=list(unmatched)))

    def test_valid_goal_and_original_text_unmatched_are_kept(self):
        v = self.verify([self.goal()], ["웨이팅 없는 곳으로"])
        assert v.goals == (Goal("night_end", "d2"),) and v.unmatched == ("웨이팅 없는 곳으로",) and v.dropped == ()

    def test_quote_not_in_text_drops_goal(self):
        v = self.verify([self.goal(quote="야경 꼭 보여 주세요")])
        assert v.goals == () and v.dropped and v.unmatched == ()

    def test_bad_parameters_drop_goal_and_move_its_quote_to_unmatched(self):
        v = self.verify([self.goal(day="d9")])
        assert v.goals == () and v.unmatched == ("마지막 날 밤엔 야경 보고 싶어요",)

    def test_reason_source_is_out_of_scope(self):
        assert self.verify([self.goal(source="reason", reaction_ids=["r1"])]).goals == ()

    def test_unmatched_must_be_substring_of_request(self):
        assert self.verify([], ["웨이팅 없는 곳으로", "가성비 좋게"]).unmatched == ("웨이팅 없는 곳으로",)

    def test_duplicates_merge_and_goal_count_is_capped(self):
        many = [self.goal(), self.goal()] + [self.goal(kind="place_on_day", day="d1", places=["p2"]),
                                             self.goal(kind="day_light", day="d1"), self.goal(kind="day_indoor", day="d1"),
                                             self.goal(kind="daily_walk_low", day=None), self.goal(kind="together", places=["p1", "p2"])]
        assert len(self.verify(many).goals) == GOALS_MAX

    def test_input_has_names_and_day_words(self):
        inp = G.goals_input(self.tr, self.TEXT)
        assert inp["last_day"] == "d2" and inp["first_day"] == "d1" and inp["days"][0] == {"day": "d1", "weekday": "월요일"}
        assert inp["places"][0]["place"] == "p1" and "lat" not in inp["places"][0]
