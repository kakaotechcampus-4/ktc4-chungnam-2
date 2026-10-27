"""mode가 생기기 전(#685)에 저장된 run을 읽어도 응답이 깨지지 않는다."""

from agent.course.service import _with_leg_modes


def test_legacy_legs_without_mode_are_read_as_walk():
    days = [{"date": "2026-11-06", "slots": [], "legs": [{"from_pin_id": "a", "to_pin_id": "b", "approx_minutes": 3}]}]
    assert _with_leg_modes(days)[0]["legs"][0]["mode"] == "walk"


def test_saved_mode_is_kept():
    days = [{"date": "2026-11-06", "slots": [], "legs": [{"from_pin_id": "a", "to_pin_id": "b", "mode": "transit", "approx_minutes": 33}]}]
    assert _with_leg_modes(days)[0]["legs"][0]["mode"] == "transit"


def test_empty_days():
    assert _with_leg_modes(None) == [] and _with_leg_modes([]) == []
