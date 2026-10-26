"""PlacesOpeningHours — places.api가 읽은 place_hours를 코스 엔진의 요일 상태로 넘긴다(#747). places는 메모리 대역(FakePlaces)이다."""

import pytest

from agent.course.gateways import PlacesOpeningHours, opening_hours_gateway
from agent.course.runner import run_course
from agent.course.tests.test_runner import build
from places.schemas import PlaceHours
from places.testing import FakePlaces

DAYS = "월화수목금토일"


@pytest.fixture()
def fake(monkeypatch):
    return FakePlaces(rows=[], hours={}).install(monkeypatch)


def week_except(*closed: str) -> dict[str, list[list[str]]]:
    return {d: ([] if d in closed else [["09:00", "18:00"]]) for d in DAYS}


def test_factory_returns_the_places_gateway():
    assert isinstance(opening_hours_gateway(), PlacesOpeningHours)


def test_gateway_reads_place_hours_as_weekday_status(fake):
    fake.hours["own-1"] = PlaceHours(hours=week_except("월"))
    fake.hours["own-2"] = PlaceHours(closed_days=["일"])

    found = PlacesOpeningHours().get_opening_hours(["own-1", "own-2"])

    assert found["own-1"] == {0: "closed", **{wd: "open" for wd in range(1, 7)}}
    assert found["own-2"] == {**{wd: "open" for wd in range(6)}, 6: "closed"}


def test_gateway_returns_none_for_a_place_without_a_row(fake):
    fake.hours["own-1"] = PlaceHours(closed_days=[])

    found = PlacesOpeningHours().get_opening_hours(["own-1", "own-9"])

    assert found["own-9"] is None and found["own-1"] is not None


def test_gateway_follows_hours_when_it_disagrees_with_closed_days(fake):
    fake.hours["own-1"] = PlaceHours(hours=week_except("화"), closed_days=["월"])

    got = PlacesOpeningHours().get_opening_hours(["own-1"])["own-1"]

    assert got[1] == "closed" and got[0] == "open"


def test_course_run_respects_the_closed_weekday(fake):
    for i in range(1, 7):
        fake.hours[f"own-{i}"] = PlaceHours(hours=week_except("월") if i == 1 else week_except())

    out = run_course(build(), "", goals_planner=None, direct_planner=None, gateway=PlacesOpeningHours())

    monday = next(d for d in out.view.days if d["date"] == "2026-10-19")
    assert "pin-1" not in [s["pin_id"] for s in monday["slots"]]       # 월요일에 쉬는 장소는 월요일에 들어가지 않는다
    assert out.view.checks == [] and out.view.violations == []          # 6곳 모두 영업시간을 알아서 「확인 필요」가 남지 않는다
