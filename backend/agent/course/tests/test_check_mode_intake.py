"""M0 보완 — ① 휴무 모름을 「확인 필요」로 두는 설정 ② 좌표 없는 핀(실시간 핀) 제외."""

from datetime import date

from agent.course import core, loop
from agent.course.intake import EXCLUDED_MESSAGE, PinInput, build_trip
from agent.course.state import initial_state
from agent.course.tests.fixtures import COURSE, KNOWN_HOURS, PLACES, TRUE_HOURS, TUE, WED, MON, trip


def check_trip():
    return trip(unknown_hours="check")


def test_확인필요_모드는_모름을_위반_목록에서_뺀다():
    t = check_trip()
    v = core.find_violations(t, COURSE, KNOWN_HOURS)
    assert v == ()                                   # p4, p5의 영업시간을 모르지만 위반이 아니다
    assert [(c.places[0], c.day) for c in core.find_checks(t, COURSE, KNOWN_HOURS)] == [("p4", "d2"), ("p5", "d2")]
    # 위반 모드(기본)에서는 같은 둘이 위반 목록에 들어 있다
    assert len(core.find_violations(trip(), COURSE, KNOWN_HOURS)) == 2
    assert [c.places[0] for c in core.find_checks(trip(), COURSE, KNOWN_HOURS)] == ["p4", "p5"]


def test_확인필요_모드의_모델_입력은_checks를_따로_보인다():
    state = initial_state(check_trip(), KNOWN_HOURS, COURSE)
    inp = loop.turn_input(state, None, 1)
    assert inp["violations"] == []
    assert inp["checks"] == [{"id": "closed:p4:d2", "place": "p4", "day": "d2", "looked_up": False},
                             {"id": "closed:p5:d2", "place": "p5", "day": "d2", "looked_up": False}]
    assert "checks" not in loop.turn_input(initial_state(trip(), KNOWN_HOURS, COURSE), None, 1)   # 기본 모드는 그대로


def test_확인필요_모드로_도식_시나리오가_끝까지_돈다():
    result = loop.run_loop(initial_state(check_trip(), KNOWN_HOURS, COURSE), decide=None, hours=TRUE_HOURS)
    assert result.outcome == "solved"                # 조회로 p4 휴무가 드러나고 옮겨서 확인 필요도 0
    assert core.find_checks(result.state.trip, result.best_course, result.state.hours) == ()
    assert "p4" not in result.best_course[1]
    look = next(s for s in result.steps if s.call["tool"] == "get_opening_hours")
    assert set(look.result.data["hard"]) == {"confirmed", "checks"}


def test_끝까지_모르면_확인필요_모드도_solved_with_checks():
    result = loop.run_loop(initial_state(check_trip(), KNOWN_HOURS, COURSE), decide=None, hours=_NobodyKnows())
    assert result.outcome == "solved_with_checks"


class _NobodyKnows:
    def get_opening_hours(self, place_ids):
        return {pid: None for pid in place_ids}


def pin(i, lat=37.5665, lng=126.978, place_id="own"):
    return PinInput(f"pin-{i}", f"{place_id}-{i}" if place_id else None, f"장소{i}", "관광지", lat, lng)


def test_좌표_없는_핀은_동선에서_빠지고_사유가_남는다():
    pins = [pin(1), pin(2, lat=None, lng=None, place_id=None), pin(3), pin(4, lat=None, lng=None, place_id=None), pin(5)]
    built = build_trip(pins, (MON, TUE))
    assert [p.alias for p in built.trip.places] == ["p1", "p2", "p3"]        # 빠진 핀은 번호를 쓰지 않는다
    assert [p.pin_id for p in built.trip.places] == ["pin-1", "pin-3", "pin-5"]
    assert [e.pin_id for e in built.excluded] == ["pin-2", "pin-4"]
    assert built.excluded[0].message == EXCLUDED_MESSAGE and built.excluded[0].reason == "NO_COORDINATES"


def test_빠진_핀은_모델_입력과_코스에_없다():
    pins = [pin(1), pin(2, lat=None, lng=None, place_id=None), pin(3, lat=37.568, lng=126.98), pin(4, lat=37.569, lng=126.981)]
    built = build_trip(pins, (MON, TUE, WED))
    state = initial_state(built.trip, {}, None)
    text = str(loop.turn_input(state, None, 1))
    assert "pin-2" not in text and "장소2" not in text
    assert sorted(p for day in state.course for p in day) == ["p1", "p2", "p3"]


def test_동선에_남은_장소가_둘보다_적으면_trip이_없다():
    built = build_trip([pin(1), pin(2, lat=None, lng=None, place_id=None), pin(3, lat=None, lng=None, place_id=None)], (MON,))
    assert built.too_few and built.trip is None and len(built.excluded) == 2
    assert build_trip([], (MON,)).too_few


def test_장소_id만_있고_좌표가_없어도_제외():
    built = build_trip([pin(1), pin(2, lat=None, lng=None), pin(3)], (MON,))
    assert [e.pin_id for e in built.excluded] == ["pin-2"]


def test_이미_조회한_곳은_횟수를_쓰지_않고_거절():
    from agent.course import tools
    from agent.course.schemas import GetOpeningHours
    state = initial_state(check_trip(), KNOWN_HOURS, COURSE)
    call = GetOpeningHours(tool="get_opening_hours", place="p5")
    state, first = tools.execute(call, state, _NobodyKnows())
    state2, second = tools.execute(call, state, _NobodyKnows())
    assert first.ok and not second.ok and second.error == "ALREADY_LOOKED_UP"
    assert state2.tool_counts["get_opening_hours"] == 1
