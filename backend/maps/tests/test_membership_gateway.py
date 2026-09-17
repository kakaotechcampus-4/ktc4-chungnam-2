"""maps/api.py::DbMembershipGateway — authz.ports.MembershipGateway를 구조적으로 만족하는지,
그리고 authz.service.resolve_principal과 실제로 엮여 동작하는지 확인한다. AllowAllMembership
스텁을 다시 심는 회귀(누구나 'member')를 여기서 잡는다.
"""

import uuid
from datetime import date

from maps.api import DbMembershipGateway
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow


def _map(db_session, *, created_by="user_1"):
    row = MapRow(
        title="t", start_date=date(2026, 10, 10), end_date=date(2026, 10, 12), created_by=created_by
    )
    db_session.add(row)
    db_session.commit()
    return row


def test_get_role_returns_owner_for_creator(db_session):
    map_row = _map(db_session, created_by="user_1")
    db_session.add(MembershipRow(map_id=map_row.id, user_id="user_1", role="owner"))
    db_session.commit()

    gateway = DbMembershipGateway(db_session)
    assert gateway.get_role(map_row.id, "user_1") == "owner"


def test_get_role_returns_member_for_joined_user(db_session):
    map_row = _map(db_session)
    db_session.add(MembershipRow(map_id=map_row.id, user_id="user_2", role="member"))
    db_session.commit()

    gateway = DbMembershipGateway(db_session)
    assert gateway.get_role(map_row.id, "user_2") == "member"


def test_get_role_returns_none_for_non_member(db_session):
    """AllowAllMembership 회귀 방지 — 실구현은 절대 기본으로 'member'를 주지 않는다."""
    map_row = _map(db_session, created_by="user_1")
    db_session.add(MembershipRow(map_id=map_row.id, user_id="user_1", role="owner"))
    db_session.commit()

    gateway = DbMembershipGateway(db_session)
    assert gateway.get_role(map_row.id, "user_2") is None


def test_get_role_returns_none_for_unknown_map(db_session):
    gateway = DbMembershipGateway(db_session)
    assert gateway.get_role(str(uuid.uuid4()), "user_1") is None


def test_resolve_principal_builds_correct_principal(db_session):
    from authz.service import resolve_principal

    map_row = _map(db_session, created_by="user_1")
    db_session.add(MembershipRow(map_id=map_row.id, user_id="user_1", role="owner"))
    db_session.commit()

    gateway = DbMembershipGateway(db_session)
    principal = resolve_principal(gateway, map_row.id, "user_1")
    assert principal.role == "owner"
    assert principal.map_id == map_row.id
    assert principal.user_id == "user_1"
