"""요청 목표 6종 — 매개변수 검증, 점수 경계, 라벨 모름 처리, 강한 기준선 비교에 끼우는 값, 모델 출력 검증."""

from types import SimpleNamespace

import pytest

from agent.course import core, goals as G
from agent.course.constants import DAILY_WALK_LOW_MAX_MIN, DAY_HAS_TAGS, GOALS_MAX
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
            # 도보 구간 하나는 25분 이하(2km)라 20·20·나머지로 이은 네 곳의 도보 합계를 맞춘다
            legs = [20, 20, minutes - 40]
            lats = [37.5]
            for m in legs:
                lats.append(lats[-1] + m * 80 / 111_000)
            tr = t(*(A(f"p{i + 1}", lat=lat) for i, lat in enumerate(lats)), days=(MON,))
            assert core.day_walk(tr, ("p1", "p2", "p3", "p4")) == minutes     # 분 계산이 이 경계를 정확히 짚는지 확인
            return tr, (("p1", "p2", "p3", "p4"),)

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


class TestMetCount:
    def test_undecidable_goals_stay_in_the_denominator_as_unmet(self):
        tr = t(A("p1", ("night_view",)), A("p2"), A("p3", OUT))
        goals = [Goal("night_end", "d1"), Goal("daily_walk_low")]
        # 첫날 마지막이 라벨 모르는 p2 → 야경은 판단 불가, 도보는 충족
        course = (("p1", "p2"), ("p3",))
        assert G.met_count(tr, course, goals) == (1, 2)
        assert G.undecidable_count(tr, course, goals) == 1
        # 코스가 달라도 분모는 목표 수로 같다 — 방식끼리 같은 분모로 비교된다
        assert G.met_count(tr, (("p2", "p1"), ("p3",)), goals) == (2, 2)
        assert G.met_count(tr, (("p3", "p2"), ("p1",)), goals)[1] == 2

    def test_no_goals_is_zero_over_zero(self):
        assert G.met_count(t(A("p1")), (("p1",), ()), []) == (0, 0)


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

    def test_one_sentence_two_requests_both_pass_with_per_clause_quotes(self):
        """#899 v3 모양: 한 문장에서 조각마다 목표 하나. 뒤 조각이 앞 조각의 날짜를 이어받아 있다."""
        text = "마지막 날엔 장소 가고, 밤엔 야경 보고 싶어요"
        goals = [self.goal(kind="place_on_day", day="d2", places=["p2"], quote="마지막 날엔 장소 가고"),
                 self.goal(kind="night_end", day="d2", quote="밤엔 야경 보고 싶어요")]
        v = G.verify_goal_set(self.tr, text, SimpleNamespace(goals=goals, unmatched=[]))
        assert v.goals == (Goal("place_on_day", "d2", ("p2",)), Goal("night_end", "d2")) and v.dropped == () and v.unmatched == ()

    def test_shortened_name_is_ok_only_if_the_alias_exists(self):
        """줄임말을 별칭으로 잇는 건 모델의 일이다. 코드는 그 별칭이 확정 리스트에 있는지만 본다(이름 비교를 하지 않는다)."""
        text = "첫날엔 줄임말 가고 싶어요"
        ok = G.verify_goal_set(self.tr, text, SimpleNamespace(
            goals=[self.goal(kind="place_on_day", day="d1", places=["p1"], quote="첫날엔 줄임말 가고 싶어요")], unmatched=[]))
        assert ok.goals == (Goal("place_on_day", "d1", ("p1",)),)
        made_up = G.verify_goal_set(self.tr, text, SimpleNamespace(
            goals=[self.goal(kind="place_on_day", day="d1", places=["p9"], quote="첫날엔 줄임말 가고 싶어요")], unmatched=[]))
        assert made_up.goals == () and made_up.unmatched == ("첫날엔 줄임말 가고 싶어요",)

    def test_input_has_names_and_day_words(self):
        inp = G.goals_input(self.tr, self.TEXT)
        assert inp["last_day"] == "d2" and inp["first_day"] == "d1" and inp["days"][0] == {"day": "d1", "weekday": "월요일"}
        assert inp["places"][0]["place"] == "p1" and "lat" not in inp["places"][0]


class TestDayHas:
    PERF = Goal("day_has", "d2", (), "performance")

    def test_normalize_validates_tag_day_and_drops_extras(self):
        tr = t(A("p1"), A("p2"))
        assert G.normalize(tr, "day_has", "d2", ["p1"], "performance") == (self.PERF, None)
        assert G.normalize(tr, "daily_walk_low", "d1", [], "performance")[0] == Goal("daily_walk_low")   # 다른 종류에서 tag는 버린다
        for day, tag in (("d2", "umbrella"), ("d2", None), (None, "performance"), ("d9", "performance")):
            goal, why = G.normalize(tr, "day_has", day, [], tag)
            assert goal is None and why

    def test_id_label_and_every_tag_maps_to_a_label_key(self):
        tr = t(A("p1"), A("p2"))
        assert self.PERF.id == "day_has:d2:performance"
        assert Goal("day_has", "d1", (), "indoor").id != Goal("day_has", "d1", (), "walkable").id
        assert G.label(tr, self.PERF) == "둘째 날 (화)에 공연 장소 넣기"
        for tag, (key, noun) in DAY_HAS_TAGS.items():
            assert key and noun and G.label(tr, Goal("day_has", "d1", (), tag)).endswith(f"{noun} 장소 넣기")

    def test_evaluate(self):
        tr = t(A("p1", ("performance",)), A("p2", OUT), A("p3"))
        assert G.evaluate(tr, (("p2",), ("p1", "p2")), self.PERF).met is True
        r = G.evaluate(tr, (("p1",), ("p2",)), self.PERF)
        assert r.met is False and r.gap == 1.0
        assert G.evaluate(tr, (("p1", "p2"), ()), self.PERF).met is False                  # 빈 날
        assert G.evaluate(tr, (("p1", "p2"), ("p3",)), self.PERF).met is None              # 그날 라벨을 아는 장소가 없다

    def test_verify_goal_set_takes_tag_and_unknown_tag_goes_to_unmatched(self):
        tr = t(A("p1", ("performance",)), A("p2"))
        text = "둘째 날 저녁엔 공연 보고 싶고, 많이 안 걸었으면 해요"
        mk = lambda tag: SimpleNamespace(kind="day_has", day="d2", places=[], tag=tag, source="request",
                                         quote="둘째 날 저녁엔 공연 보고 싶고", reaction_ids=[])
        ok = G.verify_goal_set(tr, text, SimpleNamespace(goals=[mk("performance")], unmatched=[]))
        assert ok.goals == (self.PERF,) and ok.unmatched == ()
        bad = G.verify_goal_set(tr, text, SimpleNamespace(goals=[mk("opera")], unmatched=[]))
        assert bad.goals == () and bad.unmatched == ("둘째 날 저녁엔 공연 보고 싶고",)

    def test_goals_with_same_day_and_different_tags_stay_distinct(self):
        tr = t(A("p1"))
        goals = G.truncate([Goal("day_has", "d1", (), "indoor"), Goal("day_has", "d1", (), "shopping"), Goal("day_has", "d1", (), "indoor")])
        assert len(goals) == 2

    def test_retarget_keeps_tag(self):
        assert G.retarget(self.PERF, "d1") == Goal("day_has", "d1", (), "performance")
