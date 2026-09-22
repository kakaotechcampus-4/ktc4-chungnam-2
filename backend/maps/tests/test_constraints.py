"""
DB 레벨 제약 확인 — 이 테스트는 models.py의 선언이 실제로 Postgres에 반영되는지만 본다.
픽스처가 Base.metadata.create_all(models.py 기준)로 스키마를 만들기 때문에, 0005_maps.py
마이그레이션 파일 자체가 models.py와 다른 내용을 갖고 있어도(예: CHECK 제약을 빠뜨렸어도)
이 테스트는 실행되지 않는다 — 그 드리프트는 자동 테스트가 아니라 "검증 방법"의 수동
`alembic upgrade head` 사이클로만 잡힌다(maps/for_Root.md, Antigravity 검수 지적 반영).
"""

import uuid
from datetime import date, datetime, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from maps.models import Invite as InviteRow
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow


def _map(db_session, *, created_by="user_1"):
    row = MapRow(
        title="t", start_date=date(2026, 10, 10), end_date=date(2026, 10, 12), created_by=created_by
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_ck_maps_date_order_rejects_end_before_start(db_session):
    row = MapRow(
        title="t", start_date=date(2026, 10, 12), end_date=date(2026, 10, 10), created_by="user_1"
    )
    db_session.add(row)
    with pytest.raises(IntegrityError, match="ck_maps_date_order"):
        db_session.commit()
    db_session.rollback()  # 실패한 commit() 뒤엔 세션이 deactive로 남는다 — 명시적으로 되돌린다


def test_uq_memberships_map_user_rejects_duplicate(db_session):
    map_row = _map(db_session)
    db_session.add(MembershipRow(map_id=map_row.id, user_id="user_1", role="owner"))
    db_session.commit()

    db_session.add(MembershipRow(map_id=map_row.id, user_id="user_1", role="member"))
    with pytest.raises(IntegrityError, match="uq_memberships_map_user"):
        db_session.commit()
    db_session.rollback()


def test_membership_map_id_fk_rejects_unknown_map(db_session):
    db_session.add(MembershipRow(map_id=str(uuid.uuid4()), user_id="user_1", role="owner"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_invite_used_count_defaults_to_zero(db_session):
    map_row = _map(db_session)
    invite = InviteRow(
        token="tok-" + uuid.uuid4().hex,
        map_id=map_row.id,
        created_by="user_1",
        expires_at=datetime.now(timezone.utc),
    )
    db_session.add(invite)
    db_session.commit()
    db_session.refresh(invite)
    assert invite.used_count == 0
