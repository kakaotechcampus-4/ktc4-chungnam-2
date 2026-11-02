"""#1008(K1~K3)와 #1094 후속: 목표 추출 기대값, 남은 조각, 실내 균형, 식당 알림 두 갈래, 지킬 수 없다 말 대조."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from agent.course import core, goals as G, verify, worklog
from agent.course.goals import Goal
from agent.course.tests.fixtures import trip as make_trip
from agent.course.tests.test_goals import A, t


def _goal(kind, quote, day=None, places=(), tag=None):
    return SimpleNamespace(kind=kind, day=day, places=list(places), tag=tag, quote=quote, source="request")


def _verify(tr, text, goals, unmatched=()):
    return G.verify_goal_set(tr, text, SimpleNamespace(goals=goals, unmatched=list(unmatched)))


class TestExpectedGoals:
    """모델이 내야 하는 목표(kind/day/tag)를 코드 검증이 그대로 받는지 — 실모델 출력의 기대값 고정."""

    @pytest.mark.parametrize("text,expect", [
        ("둘째 날엔 카페", Goal("day_has", "d2", (), "cafe")),
        ("카페는 마지막 날에", Goal("day_has", "d3", (), "cafe")),
        ("첫날 점심은 한식", Goal("day_has", "d1", (), "korean_food")),
    ])
    def test_category_sentences(self, text, expect):
        tr = t(A("p1", cat="카페"), A("p2"), A("p3", cat="음식점"), days=tuple(date(2026, 10, 19) + timedelta(i) for i in range(3)))
        v = _verify(tr, text, [_goal("day_has", text, expect.day, tag=expect.tag)])
        assert v.goals == (expect,) and v.unmatched == ()

    @pytest.mark.parametrize("n", [2, 3, 5])
    def test_last_day_is_the_last_date_for_any_length(self, n):
        tr = make_trip(days=tuple(date(2026, 10, 19) + timedelta(i) for i in range(n)))
        assert G.goals_input(tr, "카페는 마지막 날에")["last_day"] == f"d{n}"
        goal, why = G.normalize(tr, "day_has", f"d{n}", [], "cafe")
        assert goal is not None and core.day_index(tr, goal.day) == n - 1


class TestLeftover:
    TEXT = "마지막 날 밤에 N서울타워, 그리고 카페 많이 가고 싶어요"

    def test_piece_the_model_dropped_is_kept_as_unmatched(self):
        tr = t(A("p1"), A("p2"))
        v = _verify(tr, self.TEXT, [_goal("night_end", "마지막 날 밤에", "d2")])
        assert any("N서울타워" in u for u in v.unmatched) and all(u in self.TEXT for u in v.unmatched)

    def test_covered_and_filler_pieces_are_not_added(self):
        tr = t(A("p1"), A("p2"))
        text = "마지막 날은 실내 위주로 해주세요"
        v = _verify(tr, text, [_goal("day_indoor", "마지막 날은 실내 위주로", "d2")])
        assert v.unmatched == ()
        assert G.leftover_pieces("그리고 부탁해요", []) == []


class TestIndoorBalance:
    def test_emptying_a_day_does_not_count_as_keeping(self):
        tr = t(*[A(f"p{i}", ("is_indoor",) if i == 1 else ("quiet",)) for i in range(1, 7)])   # 6곳 2일 → 하한 2
        goal = Goal("day_indoor", "d2")
        thin = G.evaluate(tr, (("p2", "p3", "p4", "p5", "p6"), ("p1",)), goal)
        assert thin.met is False and thin.gap > 0                      # 실내 100%지만 그날이 1곳뿐이다
        assert G.evaluate(tr, (("p2", "p3", "p4"), ("p1", "p5")), goal).met is False   # 실내 비율 미달
        ok = t(*[A(f"p{i}", ("is_indoor",)) for i in range(1, 7)])
        assert G.evaluate(ok, (("p1", "p2", "p3"), ("p4", "p5", "p6")), goal).met is True


class TestMealAlert:
    def test_two_cases(self):
        none = t(A("p1"), A("p2"))
        assert "확정 리스트에 없어요" in worklog.meal_less_text(none, 1)
        short = t(A("p1"), A("p2", cat="음식점"), A("p3"), days=(core_days := t(A("p1")).days) + (date(2026, 10, 21),))
        assert "확정 리스트에 없어요" in worklog.meal_less_text(short, 2)        # 식당 1곳, 3일 — 모자라서 어쩔 수 없다
        some = t(A("p1"), A("p2", cat="음식점"), A("p3", cat="음식점"))
        text = worklog.meal_less_text(some, 1)
        assert "배정되지 않았어요" in text and "확정 리스트에 없어요" not in text


class TestCannotKeepClaim:
    def test_model_says_cannot_but_goal_is_met(self):
        tr = t(A("p1", ("is_indoor",)), A("p2", ("is_indoor",)))
        goal = Goal("day_indoor", "d1")
        res = G.evaluate_all(tr, (("p1", "p2"), ()), [goal])
        ref = SimpleNamespace(goals=[goal], goal_results=res, trip=tr, confirmed=[], checks=[])
        assert verify._goal_claims(ref, "첫날 실내 목표는 지킬 수 없어요")
        assert verify._goal_claims(ref, "실내 위주로 지키기 어려워요")
