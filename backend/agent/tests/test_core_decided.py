"""core.decided_within_24h(#613, 명세 12.9) — 제안 created_at부터 24시간 안에 확정이 생겼는가. 유형별 참과 거짓, 경계."""

from datetime import datetime, timedelta, timezone

import pytest

from agent import core

CREATED = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)


def target(diagnosis, *, category=None, pin_id=None, claims=(), actions=()):
    return core.DecisionTarget(id="sug", diagnosis=diagnosis, category=category, pin_id=pin_id, claims=list(claims),
                               actions=list(actions), created_at=CREATED)


def confirmed(pin_id="p1", category="카페", *, after=timedelta(hours=1)):
    return core.Confirmation(pin_id=pin_id, category=category, added_at=CREATED + after)


def ref(pin_id, n=2):
    return {"id": f"c{n}", "kind": "ref", "object": "pin", "ref_id": pin_id}


def show_pins(*pin_ids):
    return {"index": 0, "type": "show_pins", "label": "미확인 핀 보기", "params": {"pin_ids": list(pin_ids)}}


@pytest.mark.parametrize("diagnosis", ["category_gap", "stall"])
def test_category_types_count_a_confirmed_pin_of_that_category(diagnosis):
    assert core.decided_within_24h(target(diagnosis, category="카페"), [confirmed(category="카페")]) is True
    assert core.decided_within_24h(target(diagnosis, category="카페"), [confirmed(category="음식점")]) is False
    assert core.decided_within_24h(target(diagnosis, category="카페"), []) is False


def test_category_types_cannot_count_a_pin_without_category():
    """분류를 읽지 못한 핀(삭제된 핀 등)은 카테고리 유형에서 세지 못한다."""
    assert core.decided_within_24h(target("category_gap", category="카페"), [confirmed(category=None)]) is False


def test_split_counts_only_its_pin():
    sug = target("split", category="카페", pin_id="p1")
    assert core.decided_within_24h(sug, [confirmed("p1")]) is True
    assert core.decided_within_24h(sug, [confirmed("p2", category="카페")]) is False   # 같은 카테고리의 다른 핀


def test_no_reaction_counts_any_pointed_pin():
    sug = target("no_reaction", claims=[ref("p1", 2), ref("p2", 3)], actions=[show_pins("p1", "p2")])
    assert core.decided_within_24h(sug, [confirmed("p2", category=None)]) is True   # 분류 없이 핀으로 본다
    assert core.decided_within_24h(sug, [confirmed("p9")]) is False


def test_no_reaction_reads_pins_from_claims_or_show_pins():
    assert core.pointed_pin_ids(target("no_reaction", claims=[ref("p1")], actions=[show_pins("p2")])) == {"p1", "p2"}
    assert core.decided_within_24h(target("no_reaction", actions=[show_pins("p2")]), [confirmed("p2")]) is True


@pytest.mark.parametrize(("after", "expected"), [
    (timedelta(0), True),                                  # 제안과 같은 시각
    (timedelta(hours=24), True),                           # 24시간 정각까지
    (timedelta(hours=24, seconds=1), False),               # 24시간 1초 뒤
    (-timedelta(seconds=1), False),                        # 제안 전 확정은 세지 않는다
])
def test_window_is_24_hours_from_created_at(after, expected):
    for sug in (target("category_gap", category="카페"), target("split", pin_id="p1")):
        assert core.decided_within_24h(sug, [confirmed("p1", "카페", after=after)]) is expected


def test_one_confirmation_in_window_is_enough():
    late = confirmed("p1", after=timedelta(hours=30))
    inside = confirmed("p1", after=timedelta(hours=2))
    assert core.decided_within_24h(target("split", pin_id="p1"), [late, inside]) is True


def test_unknown_diagnosis_raises():
    with pytest.raises(ValueError):
        core.decided_within_24h(target("other"), [])
