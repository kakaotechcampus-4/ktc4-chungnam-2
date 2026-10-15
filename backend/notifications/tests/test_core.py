"""core.py — 문장, 커서, 설정 합치기. DB가 필요 없다."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from notifications import core


def test_every_type_has_a_message_and_it_fits_the_spec_limit():
    for type in core.TYPES:
        text = core.compose_message(type, actor_name="지우", map_title="부산 여행")
        assert text and len(text) <= core.MESSAGE_MAX


def test_message_examples():
    assert core.compose_message("pin_reaction", actor_name="지우", reaction="like") == "지우님이 내 핀에 ♥를 남겼어요"
    assert core.compose_message("pin_reaction", actor_name="지우", reaction="dislike") == "지우님이 내 핀에 🚫 반대를 남겼어요"
    assert core.compose_message("pin_reaction", actor_name="지우") == "지우님이 내 핀에 반응을 남겼어요"
    assert core.compose_message("member_joined", actor_name="  ") == "구성원님이 지도에 들어왔어요"
    assert core.compose_message("map_deleted", map_title="부산 여행") == "'부산 여행' 지도가 삭제되었어요"
    assert core.compose_message("map_deleted") == "지도가 삭제되었어요"


def test_message_never_takes_a_reason_or_memo():
    """문장을 만드는 함수에 사유·메모를 받는 인자가 없다 — 새 인자가 생기면 이 테스트가 눈에 띄게 한다."""
    import inspect

    params = set(inspect.signature(core.compose_message).parameters)
    assert params == {"type", "actor_name", "map_title", "reaction"}


def test_long_values_are_clipped():
    text = core.compose_message("member_joined", actor_name="가" * 500)
    assert len(text) == core.MESSAGE_MAX and text.endswith("…")
    assert len(core.compose_message("map_deleted", map_title="나" * 500)) <= core.MESSAGE_MAX


def test_unknown_type_is_rejected():
    with pytest.raises(ValueError):
        core.compose_message("pin_deleted")
    assert core.is_known_type("pin_reaction") and not core.is_known_type("pin_deleted")


def test_cursor_roundtrip_is_url_safe():
    at = datetime(2026, 10, 15, 12, 30, 1, 123456, tzinfo=timezone(timedelta(hours=9)))
    nid = uuid.uuid4()
    cursor = core.encode_cursor(at, nid)
    assert all(c.isalnum() or c in "-_" for c in cursor)    # '+'·'='가 없어 쿼리 문자열에 그대로 실을 수 있다
    assert core.decode_cursor(cursor) == (at, nid)


@pytest.mark.parametrize("bad", ["", "!!!", "aGVsbG8", "MjAyNi0xMC0xNXxub3QtYS11dWlk"])
def test_bad_cursor_raises_value_error(bad):
    with pytest.raises(ValueError):
        core.decode_cursor(bad)


def test_cursor_without_timezone_is_rejected():
    import base64

    raw = base64.urlsafe_b64encode(f"2026-10-15T12:00:00|{uuid.uuid4()}".encode()).decode()
    with pytest.raises(ValueError):
        core.decode_cursor(raw)


def test_parse_ids_drops_malformed_ids():
    good = uuid.uuid4()
    assert core.parse_ids([str(good), "not-a-uuid", ""]) == [good]


def test_effective_prefs_fills_defaults_in_declared_order():
    prefs = core.effective_prefs({"map_deleted": False})
    assert [t for t, _ in prefs] == list(core.TYPES)
    assert dict(prefs) == {**{t: True for t in core.TYPES}, "map_deleted": False}


def test_last_wins_on_duplicates():
    assert core.last_wins([("pin_reaction", False), ("pin_reaction", True)]) == {"pin_reaction": True}
