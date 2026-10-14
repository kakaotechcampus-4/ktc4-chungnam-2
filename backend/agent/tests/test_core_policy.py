"""개입 정책(명세 12.3, 17절 6번)과 대체 순위(7절), 다음 점검 시각(12.4), 정책 파일 로더.

fingerprint 중복, 백오프 2, 6, 24시간과 수락 초기화와 만료 미포함, no_reaction 하루 1회, 모델 상한(구성원 수 × 4,
KST 자정), 상한 도달 시 코드 유형 통과와 fallback_order.
"""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from agent import core
from agent.tests.snaps import NOW, hours, member, pin, react, snap

SEC = timedelta(seconds=1)
SNAP3 = snap(members=("u1", "u2", "u3"))


def _sig(diagnosis="stall", category="음식점", *, evidence=("r1",), elapsed_ratio=None, sid="s1"):
    sig = core.make_signal(diagnosis, category=category, evidence=[(e, "against", NOW) for e in evidence],
                           features={"elapsed_ratio": elapsed_ratio, "recent_dismissals": 0})
    return replace(sig, id=sid)


def _past(status, *, diagnosis="stall", category="음식점", fingerprint="fp-other", created_at=None,
          resolved_at=None, expires_at=None, sid="h"):
    return core.PastSuggestion(
        id=sid, diagnosis=diagnosis, category=category, fingerprint=fingerprint, status=status,
        created_at=created_at or NOW - hours(30), resolved_at=resolved_at, expires_at=expires_at,
    )


def _check(signals, *suggestions, runs_today=0, snapshot=SNAP3, superseding=()):
    hist = core.History(suggestions=tuple(suggestions), model_runs_today=runs_today)
    passed, blocked = core.check_policy(signals, hist, snapshot, NOW, superseding=superseding)
    return [s.id for s in passed], {b.signal_id: b.reason for b in blocked}


# ---------------------------------------------------------------- 1. 활성 제안

def test_active_suggestion_blocks_everything():
    signals = [_sig(sid="s1"), _sig("category_gap", "카페", sid="s2")]

    assert _check(signals, _past("active", sid="act")) == ([], {"s1": "active_exists", "s2": "active_exists"})


def test_active_being_superseded_does_not_block():
    assert _check([_sig()], _past("active", sid="act"), superseding={"act"}) == (["s1"], {})


# ---------------------------------------------------------------- 2. fingerprint 중복

@pytest.mark.parametrize("status", ["accepted", "dismissed", "expired"])
def test_same_fingerprint_closed_by_people_is_duplicate(status):
    sig = _sig()
    old = _past(status, fingerprint=sig.fingerprint, resolved_at=NOW - hours(100))

    assert _check([sig], old) == ([], {"s1": "duplicate"})


def test_superseded_fingerprint_can_be_suggested_again():
    sig = _sig()
    assert _check([sig], _past("superseded", fingerprint=sig.fingerprint)) == (["s1"], {})


# ---------------------------------------------------------------- 3. 백오프

@pytest.mark.parametrize(("dismissals", "hours_"), [(1, 2), (2, 6), (3, 24), (4, 24)])
def test_backoff_hours_by_streak(dismissals, hours_):
    last = NOW - hours(1)
    history = [_past("dismissed", resolved_at=last - hours(i), sid=f"d{i}") for i in range(dismissals)]

    assert core.backoff_until(history, "stall", "음식점") == last + hours(hours_)


def test_backoff_blocks_until_boundary():
    history_at = lambda resolved: _past("dismissed", resolved_at=resolved)   # noqa: E731

    assert _check([_sig()], history_at(NOW - hours(2) + SEC)) == ([], {"s1": "backoff"})
    assert _check([_sig()], history_at(NOW - hours(2))) == (["s1"], {})


def test_accept_resets_streak():
    history = [
        _past("dismissed", resolved_at=NOW - hours(1), sid="d1"),
        _past("accepted", resolved_at=NOW - hours(5), sid="a"),
        _past("dismissed", resolved_at=NOW - hours(10), sid="d2"),
        _past("dismissed", resolved_at=NOW - hours(20), sid="d3"),
    ]
    assert core.backoff_until(history, "stall", "음식점") == NOW - hours(1) + hours(2)


def test_expired_and_superseded_are_not_counted():
    history = [
        _past("dismissed", resolved_at=NOW - hours(1), sid="d1"),
        _past("expired", sid="e"),
        _past("superseded", sid="s"),
        _past("dismissed", resolved_at=NOW - hours(3), sid="d2"),
    ]
    assert core.backoff_until(history, "stall", "음식점") == NOW - hours(1) + hours(6)
    assert core.backoff_until([_past("expired")], "stall", "음식점") is None


def test_backoff_is_per_diagnosis_and_category():
    history = [_past("dismissed", resolved_at=NOW - hours(1))]

    assert core.backoff_until(history, "stall", "카페") is None
    assert core.backoff_until(history, "split", "음식점") is None


def test_passed_signal_carries_recent_dismissals():
    history = [_past("dismissed", resolved_at=NOW - hours(30), sid="d1"),
               _past("dismissed", resolved_at=NOW - hours(40), sid="d2")]
    hist = core.History(suggestions=tuple(history))

    [passed], _ = core.check_policy([_sig()], hist, SNAP3, NOW)

    assert passed.features["recent_dismissals"] == 2


# ---------------------------------------------------------------- 4. no_reaction 하루 1회

def test_no_reaction_once_per_kst_day():
    sig = _sig("no_reaction", None, evidence=("p9",))
    day_start = core.kst_day_start(NOW)

    today = _past("superseded", diagnosis="no_reaction", category=None, created_at=day_start)
    assert _check([sig], today) == ([], {"s1": "daily_limit"})

    yesterday = _past("dismissed", diagnosis="no_reaction", category=None, created_at=day_start - SEC,
                      resolved_at=day_start - SEC - hours(30))
    assert _check([sig], yesterday) == (["s1"], {})


# ---------------------------------------------------------------- 5. 모델 사용 상한

def test_model_cap_is_members_times_four():
    assert core.model_cap_reached(11, 3) is False
    assert core.model_cap_reached(12, 3) is True
    assert core.model_cap_reached(0, 0) is True   # 구성원이 없으면 상한 0


def test_kst_midnight_boundary():
    before = datetime(2026, 10, 15, 14, 59, 59, tzinfo=timezone.utc)   # KST 10/15 23:59:59
    after = datetime(2026, 10, 15, 15, 0, 0, tzinfo=timezone.utc)      # KST 10/16 00:00:00

    assert core.kst_day_start(before) == datetime(2026, 10, 14, 15, 0, tzinfo=timezone.utc)
    assert core.kst_day_start(after) == after
    with pytest.raises(ValueError):
        core.kst_day_start(datetime(2026, 10, 15, 12, 0))


def test_cap_blocks_model_types_and_code_types_pass():
    signals = [
        _sig("stall", "음식점", sid="s1"), _sig("split", "카페", evidence=("r5",), sid="s2"),
        _sig("no_reaction", None, evidence=("p1",), sid="s3"), _sig("category_gap", "관광지", sid="s4"),
    ]

    assert _check(signals, runs_today=11) == (["s1", "s2", "s3", "s4"], {})
    assert _check(signals, runs_today=12) == (["s3", "s4"], {"s1": "model_cap", "s2": "model_cap"})


def test_cap_then_fallback_order_picks_code_type():
    signals = [
        _sig("stall", "음식점", sid="s1"), _sig("no_reaction", None, evidence=("p1",), sid="s2"),
        _sig("category_gap", "관광지", sid="s3"),
    ]
    hist = core.History(model_runs_today=12)
    passed, _ = core.check_policy(signals, hist, SNAP3, NOW)

    assert [s.id for s in core.fallback_order(passed, core.load_policy())] == ["s3", "s2"]


def test_first_matching_reason_wins():
    """중복이면서 백오프 중이어도 이유는 하나(앞 단계)만 남는다."""
    sig = _sig()
    history = [_past("dismissed", fingerprint=sig.fingerprint, resolved_at=NOW - hours(1))]

    assert _check([sig], *history, runs_today=99) == ([], {"s1": "duplicate"})


# ---------------------------------------------------------------- 대체 순위와 정책 파일 (7절)

def test_fallback_order_weights_then_elapsed_ratio():
    signals = [
        _sig("no_reaction", None, evidence=("p1",), sid="s1"),
        _sig("category_gap", "카페", sid="s2"),
        _sig("split", "음식점", elapsed_ratio=1.2, sid="s3"),
        _sig("stall", "카페", elapsed_ratio=None, sid="s4"),
        _sig("stall", "음식점", elapsed_ratio=2.5, sid="s5"),
    ]

    order = core.fallback_order(signals, core.load_policy())

    assert [s.id for s in order] == ["s5", "s3", "s4", "s2", "s1"]


def test_policy_file_matches_spec_draft():
    policy = core.load_policy()

    assert policy.version == 1
    assert dict(policy.weights) == {"stall": 3, "split": 3, "category_gap": 2, "no_reaction": 1}
    assert (policy.never_first, policy.always_first) == ((), ())
    assert len(policy.principles) == 3


def test_policy_rejects_missing_weight_or_unknown_rule():
    base = {"version": 1, "principles": [], "rules": {},
            "weights": {"stall": 3, "split": 3, "category_gap": 2, "no_reaction": 1}}
    with pytest.raises(ValueError):
        core.parse_policy({**base, "weights": {"stall": 3}})
    with pytest.raises(ValueError):
        core.parse_policy({**base, "rules": {"never_first": ["route"]}})


# ---------------------------------------------------------------- 다음 점검 시각 (12.4)

TH = hours(3)


def test_next_check_at_picks_earliest_future_deadline():
    s = snap(
        members=("u1", "u2", member("u3", joined_at=NOW - hours(2))),
        pins=[pin("f1"), pin("c1", category="카페")],
        # 음식점 정체 t0 → NOW + 2h. 카페는 정체 t0와 갈림(전원 아님)의 마지막 반응 → NOW + 0.5h.
        # u3의 f1 반응 공백 대상 → 합류 + 3h = NOW + 1h
        reactions=[react("a1", "f1", "u2", "against", NOW - hours(1)),
                   react("l1", "c1", "u2", "like", NOW - hours(2.5)),
                   react("a2", "c1", "u3", "against", NOW - hours(2.5))],
    )
    assert core.next_check_at(s, core.History(), NOW, TH) == NOW + hours(0.5)


def test_next_check_at_includes_active_expiry_and_ignores_past():
    active = _past("active", expires_at=NOW + hours(5))
    quiet = snap(members=("u1",), pins=[pin("f1")])
    assert core.next_check_at(quiet, core.History(suggestions=(active,)), NOW, TH) == NOW + hours(5)
    assert core.next_check_at(quiet, core.History(), NOW, TH) is None
