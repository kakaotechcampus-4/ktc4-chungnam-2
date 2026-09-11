import json
from dataclasses import dataclass

from realtime.router import _parse_last_event_id, _sse_control_event, _sse_format


def test_parse_last_event_id_valid():
    assert _parse_last_event_id("42") == 42


def test_parse_last_event_id_missing():
    assert _parse_last_event_id(None) is None


def test_parse_last_event_id_invalid_falls_back_to_none():
    assert _parse_last_event_id("abc") is None


@dataclass(frozen=True)
class _Row:
    seq: int
    type: str
    map_id: str
    payload: dict


def test_sse_format_uses_seq_as_id_and_json_payload():
    row = _Row(seq=7, type="pin.created", map_id="map1", payload={"pin_id": "p1"})
    out = _sse_format(row)
    assert out.startswith("id: 7\n")
    assert "event: pin.created\n" in out
    data_line = next(line for line in out.splitlines() if line.startswith("data: "))
    assert json.loads(data_line[len("data: "):]) == {
        "type": "pin.created", "map_id": "map1", "payload": {"pin_id": "p1"},
    }


def test_sse_control_event_carries_type():
    out = _sse_control_event("replay_truncated")
    assert "event: control\n" in out
    data_line = next(line for line in out.splitlines() if line.startswith("data: "))
    assert json.loads(data_line[len("data: "):]) == {"type": "replay_truncated"}
