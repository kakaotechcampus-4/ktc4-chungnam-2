"""#1128 1·2·5번: 영업 확인 문장의 곳 수, 지휘 문장의 장소·날짜 검증, 빈 요청·맡김·시간·하루 비우기의 이유 문장, 「매일 카페」."""

from types import SimpleNamespace

import pytest

from agent.course import core, goals as G, verify, worklog
from agent.course.gateways import NullOpeningHours
from agent.course.goals import Goal
from agent.course.runner import run_course
from agent.course.tests.fixtures import ALL_OPEN, PLACES, trip
from agent.course.tests.test_runner import build
from llm.schemas import CourseGoal, CourseGoalSet

COURSE = (("p1", "p2"), ("p3", "p4", "p5"), ("p6",))


def _goal(kind, quote, day=None, places=(), tag=None):
    return SimpleNamespace(kind=kind, day=day, places=list(places), tag=tag, quote=quote, source="request")


def _verify(text, goals=(), unmatched=()):
    return G.verify_goal_set(trip(), text, SimpleNamespace(goals=list(goals), unmatched=list(unmatched)))


def _opening(goals=(), unmatched=()):
    return worklog.Narrator(trip(), goals, unmatched).opening()[0].text


class TestChecksCount:
    def test_closing_sentence_counts_unknown_places(self):
        out = run_course(build(), "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        last = out.view.steps[-1]["text"]
        assert out.view.outcome == "solved_with_checks"
        assert "영업시간을 모르는 6곳은 가게에 확인해 주세요." in last


class TestCheckDayClaim:
    """「{p4}의 {d2} 영업 여부」 — 그 장소가 그 코스의 그날에 있어야 한다(스테이징: 낙원아구찜이 셋째 날인데 「둘째 날」)."""

    def ref(self):
        t = trip()
        hours = {p.alias: ALL_OPEN for p in PLACES if p.alias != "p6"}       # p6(셋째 날)은 영업 여부를 모른다
        return verify.Reference(t, hours, COURSE, core.find_violations(t, COURSE, hours), (), "후보", 1)

    def test_wrong_day_is_blocked(self):
        found = verify.problems(self.ref(), "확정 위반은 없지만 {p6}의 {d2} 영업 여부가 확인되지 않아 이 후보로 마무리해요.")
        assert any("영업 여부를 말했지만 결과에서는 셋째 날" in f for f in found), found

    def test_right_day_passes(self):
        assert verify.problems(self.ref(), "확정 위반은 없지만 {p6}의 {d3} 영업 여부가 확인되지 않아 이 후보로 마무리해요.") == []

    def test_plan_is_not_a_claim(self):
        assert verify.problems(self.ref(), "{p6}을 {d2}로 옮기면 영업 여부를 다시 봐야 해요.") == []

    def test_blocked_sentence_is_replaced_by_code(self):
        g = verify.guard(self.ref(), "{p6}의 {d1} 영업 여부가 확인되지 않았어요.")
        assert g is not None and "영업 확인이 필요한 곳은 1곳이에요." in g.replacement


class TestRequestPieces:
    def test_empty_request_states_the_default_basis(self):
        assert _opening() == "이렇게 이해했어요: " + worklog.NO_GOALS_OPENING
        out = run_course(build(), "", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        assert out.view.steps[-1]["text"].startswith(worklog.NO_GOALS_CLOSING)

    @pytest.mark.parametrize("text", ["알아서 잘 짜줘", "알아서 잘 짜주세요", "그냥 알아서 해줘", "적당히 맡길게요"])
    def test_delegation_is_not_unmatched(self, text):
        assert G.is_delegation(text)
        assert _verify(text, unmatched=[text]).unmatched == ()
        assert _verify(text).unmatched == ()                               # 모델이 아무것도 안 내도 남은 조각으로 잡히지 않는다

    def test_delegation_with_a_wish_is_not_delegation(self):
        assert not G.is_delegation("알아서 카페 많이 넣어줘")

    def test_delegation_without_model_matches_empty_request(self):
        out = run_course(build(), "알아서 잘 짜줘", goals_planner=None, direct_planner=None, gateway=NullOpeningHours())
        assert out.view.unmatched == [] and out.view.steps[0]["text"] == "이렇게 이해했어요: " + worklog.NO_GOALS_OPENING

    @pytest.mark.parametrize("piece,reason", [
        ("점심 12시에 큰 기와집 예약했어", G.TIME_GIVEN),
        ("오후 세 시엔 박물관", G.TIME_GIVEN),
        ("화요일엔 아무것도 안 하고 쉴래", G.REST_DAY),
        ("마지막 날은 비워 주세요", G.REST_DAY),
        ("웨이팅 없는 곳으로", None),
        ("하루 걷는 시간 줄여 주세요", None),
        ("경복궁 예약했어", None),                                          # 「예약」만으로는 시간 지정이 아니다
        ("저녁에 한정식 예약했어요", G.TIME_GIVEN),
        ("카페에서 휴식", None),                                             # 「휴식」만으로는 하루 비우기가 아니다
        ("화요일은 휴식", G.REST_DAY),
    ])
    def test_piece_reason(self, piece, reason):
        assert G.piece_reason(piece) == reason

    def test_reason_sentence_is_fixed_and_has_no_user_text(self):
        piece = "점심 12시에 큰 기와집 예약했어"
        text = _opening(unmatched=(piece,))
        assert G.PIECE_REASONS[G.TIME_GIVEN] in text and piece not in text and "판단할 수 없어요" not in text
        rest = "화요일엔 아무것도 안 하고 쉴래"
        text = _opening(unmatched=(rest,))
        assert text.endswith("확정 장소를 모든 날에 나눠요. 하루를 비우려면 장소를 줄여 주세요.") and rest not in text

    def test_unknown_piece_keeps_the_old_sentence(self):
        assert "「웨이팅 없는 곳으로」는 그대로는 판단할 수 없어요." in _opening(unmatched=("웨이팅 없는 곳으로",))


class TestDailyCafe:
    TEXT = "카페는 매일 하나씩"

    def test_daily_day_has_becomes_one_goal_per_day(self):
        v = _verify(self.TEXT, [_goal("day_has", self.TEXT, tag="cafe")])
        assert v.goals == tuple(Goal("day_has", f"d{i}", (), "cafe") for i in (1, 2, 3)) and v.unmatched == ()

    def test_dateless_day_has_without_daily_word_stays_unmatched(self):
        v = _verify("카페 가고 싶어요", [_goal("day_has", "카페 가고 싶어요", tag="cafe")])
        assert v.goals == () and v.unmatched == ("카페 가고 싶어요",)

    def test_other_goals_come_first_under_goals_max(self):
        text = "카페는 매일 하나씩, 둘째 날은 여유 있게, 첫날 마지막은 야경"
        v = _verify(text, [
            _goal("day_has", "카페는 매일 하나씩", tag="cafe"),
            _goal("day_light", "둘째 날은 여유 있게", "d2"),
            _goal("night_end", "첫날 마지막은 야경", "d1"),
        ])
        assert v.goals == (Goal("day_light", "d2"), Goal("night_end", "d1"),
                           Goal("day_has", "d1", (), "cafe"), Goal("day_has", "d2", (), "cafe"))

    def test_fewer_cafes_than_days_shows_unmet(self):
        def planner(_input):
            return CourseGoalSet(goals=[CourseGoal(kind="day_has", day=None, tag="cafe", source="request", quote=self.TEXT)], unmatched=[])

        out = run_course(build(), self.TEXT, goals_planner=planner, direct_planner=None, gateway=NullOpeningHours())
        cafe_goals = [g for g in out.view.goals if g["id"].startswith("day_has:")]
        assert len(cafe_goals) == 3
        assert sum(g["met"] is True for g in cafe_goals) == 2                # 카페 2곳(장소2, 장소5)에 날짜는 3일
