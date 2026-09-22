"""maps/core.py — 순수 함수만 테스트한다. DB·TestClient·mock 없음, 밀리초 단위로 끝난다.
틀리면 실패하는 것만 검증한다(존재/통과가 아니라 실제로 잘못된 동작을 잡는지)."""

from datetime import date, datetime, timedelta, timezone
from typing import get_args

import pytest

from authz.policy import Role
from common.errors import AppError
from maps import core
from maps.models import MembershipRole
from maps.schemas import Member


def test_end_date_equal_to_start_date_is_accepted():
    """당일치기 여행 — CHECK 제약과 같은 `>=`. `>`로 잘못 쓰면 이 테스트가 깨진다."""
    result = core.validate_map_create("부산", date(2026, 10, 10), date(2026, 10, 10))
    assert result.end_date == result.start_date


def test_end_date_before_start_date_is_validation_error():
    with pytest.raises(AppError) as exc_info:
        core.validate_map_create("부산", date(2026, 10, 10), date(2026, 10, 9))
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_title_is_stripped():
    result = core.validate_map_create("  부산  ", date(2026, 10, 10), date(2026, 10, 12))
    assert result.title == "부산"


def test_whitespace_only_title_is_rejected():
    with pytest.raises(AppError) as exc_info:
        core.validate_map_create("   ", date(2026, 10, 10), date(2026, 10, 12))
    assert exc_info.value.code == "VALIDATION_ERROR"


def test_invite_exactly_at_expiry_is_rejected():
    """now == expires_at 경계 — >= 비교라 만료 시각 정각도 거부된다."""
    expires_at = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(AppError) as exc_info:
        core.check_invite_acceptable(expires_at, now=expires_at)
    assert exc_info.value.code == "UNAUTHORIZED"


def test_invite_one_microsecond_before_expiry_is_accepted():
    expires_at = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    now = expires_at - timedelta(microseconds=1)
    core.check_invite_acceptable(expires_at, now=now)  # 예외 없이 통과해야 한다


def test_check_invite_acceptable_rejects_naive_datetime():
    """naive datetime을 그냥 받으면 KST/UTC 혼동으로 9시간 오차가 조용히 생길 수 있다."""
    naive = datetime(2026, 10, 1, 12, 0, 0)
    aware = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        core.check_invite_acceptable(naive, now=aware)
    with pytest.raises(ValueError):
        core.check_invite_acceptable(aware, now=naive)


def test_invite_expires_at_is_ttl_after_now_and_keeps_tz():
    now = datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc)
    expires_at = core.invite_expires_at(now)
    assert expires_at - now == timedelta(days=7)
    assert expires_at.tzinfo is not None


def test_invite_expires_at_rejects_naive_now():
    with pytest.raises(ValueError):
        core.invite_expires_at(datetime(2026, 10, 1, 12, 0, 0))


@pytest.mark.parametrize("base", ["http://x", "http://x/"])
def test_build_invite_url_has_no_double_slash(base):
    url = core.build_invite_url(base, "tok123")
    assert url == "http://x/invites/tok123"
    assert "//invites" not in url.replace("http://", "")


def test_map_response_omits_confirmed_count_when_unknown():
    """0을 보내면 '확정 3개인 지도가 0개로 보이는' 거짓말이 된다 — 키 자체가 없어야 한다."""
    record = core.MapRecord(id="m1", title="부산", start_date=date(2026, 10, 10), end_date=date(2026, 10, 12))
    response = core.to_map_response(record, member_count=1, confirmed_count=None)
    dumped = response.model_dump(exclude_none=True)
    assert "confirmed_count" not in dumped


def test_map_response_includes_confirmed_count_when_known():
    record = core.MapRecord(id="m1", title="부산", start_date=date(2026, 10, 10), end_date=date(2026, 10, 12))
    response = core.to_map_response(record, member_count=1, confirmed_count=3)
    assert response.model_dump(exclude_none=True)["confirmed_count"] == 3


def test_member_response_omits_display_name_and_online_when_unknown():
    """user_id로 display_name을 대체하거나 online=False로 채우면 그럴싸해 보이는 거짓
    fallback이 된다 — 둘 다 응답에서 빠져야 한다."""
    response = core.to_member_response("user_1", display_name=None, online=None)
    assert response.model_dump(exclude_none=True) == {"user_id": "user_1"}


def test_member_joined_event_shape():
    member = Member(user_id="user_2", display_name=None, online=None)
    event = core.member_joined_event("map_1", member)
    assert event.channel == "public"
    assert event.type == "member.joined"
    assert event.recipient_user_id is None
    assert event.payload == {"user_id": "user_2"}


def test_membership_role_enum_matches_authz_policy_role():
    """DB enum이 authz.policy.Role과 어긋나면 여기서 잡는다 — 루트가 permissions.md에
    역할을 추가/변경했는데 이 모듈의 DB enum이 안 따라가는 드리프트 방지."""
    assert set(get_args(Role)) == set(MembershipRole.enums)
