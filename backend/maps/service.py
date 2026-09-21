"""
얇은 I/O 셸 — 입력 수집 → core 호출 → DB 반영/응답 변환만 한다(docs/code-quality.md).
분기·계산 로직은 maps/core.py로 위임한다. 커밋하지 않는다 — common.database.get_db가
요청당 한 번 커밋하는 유일한 지점이다(db.flush()만 쓴다).
"""

import secrets
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from common.errors import AppError
from common.events import record_event
from maps import core
from maps.models import Invite as InviteRow
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow
from maps.schemas import Invite, Map, MapCreateRequest, Member

INVITE_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) — 256비트, 소지자가 곧 가입 권한을 갖는
# bearer capability라 uuid4가 아니라 secrets 모듈을 쓴다(예측 불가능성이 목적, 유일성이 아니다).


def _member_count(db: Session, map_id: str) -> int:
    return db.execute(
        select(func.count()).select_from(MembershipRow).where(MembershipRow.map_id == map_id)
    ).scalar_one()


def get_map_or_404(db: Session, map_id: str) -> MapRow:
    row = db.execute(select(MapRow).where(MapRow.id == map_id)).scalar_one_or_none()
    if row is None:
        raise AppError("NOT_FOUND")
    return row


def _map_response(db: Session, map_row: MapRow) -> Map:
    record = core.MapRecord(
        id=map_row.id, title=map_row.title, start_date=map_row.start_date, end_date=map_row.end_date
    )
    return core.to_map_response(
        record, member_count=_member_count(db, map_row.id), confirmed_count=None
    )


def create_map(db: Session, *, req: MapCreateRequest, creator_id: str) -> Map:
    """maps 행 + owner 멤버십 행을 같은 트랜잭션에 만든다. 멤버십이 빠지면 생성자가 자기
    지도의 비구성원이 되어 이후 모든 요청이 404가 된다 — 테스트가 DB를 직접 확인한다.

    seeding 프리시딩 잡을 여기서 큐잉하지 않는다: architecture.md 3절은 그 잡의 지역을
    "첫 핀 좌표로 확정"한다고 정의하는데, 이 시점엔 핀이 0개라 region을 채울 방법이 없다
    (maps/CLAUDE.md 완료 정의와의 모순 — maps/for_Root.md 항목 2로 보고). 로그만 찍는 no-op
    훅은 완료 정의 체크박스만 채우는 가짜 구현이라 만들지 않는다."""
    new_map = core.validate_map_create(req.title, req.start_date, req.end_date)

    map_row = MapRow(
        title=new_map.title, start_date=new_map.start_date, end_date=new_map.end_date,
        created_by=creator_id,
    )
    db.add(map_row)
    db.flush()  # map_row.id 확정 — 멤버십 행이 참조해야 한다

    db.add(MembershipRow(map_id=map_row.id, user_id=creator_id, role="owner"))
    db.flush()

    return _map_response(db, map_row)


def get_map_response(db: Session, *, map_id: str) -> Map:
    map_row = get_map_or_404(db, map_id)
    return _map_response(db, map_row)


def create_invite(db: Session, *, map_id: str, creator_id: str, base_url: str) -> Invite:
    """base_url은 router가 만든 값을 그대로 받는다(request.base_url 기반) — FE 오리진의
    정본이 없어(maps/for_Root.md 항목 8) 이 링크는 지금 브라우저로 바로 열 수 있는 페이지가
    아니라는 한계가 있다. 값을 지어내는 대신 그 사실을 그대로 안고 간다."""
    token = secrets.token_urlsafe(INVITE_TOKEN_BYTES)
    now = datetime.now(timezone.utc)
    expires_at = core.invite_expires_at(now)

    invite_row = InviteRow(token=token, map_id=map_id, created_by=creator_id, expires_at=expires_at)
    db.add(invite_row)
    db.flush()

    return Invite(token=token, url=core.build_invite_url(base_url, token), expires_at=expires_at)


def accept_invite(db: Session, *, token: str, user_id: str) -> Map:
    """순서가 핵심이다 — 존재·만료 확인 → 멤버십 upsert → used_count/이벤트(실제 가입 시에만).
    ON CONFLICT DO NOTHING을 쓴다(DO UPDATE 아님) — owner가 자기 초대를 열어도 role이
    조용히 'member'로 강등되지 않는다. shortlist/service.py::add_item의 savepoint+rollback
    패턴을 여기선 쓰지 않는다 — 그 패턴의 db.rollback()은 같은 요청의 앞선 쓰기를 전부
    날리는데, 여기선 boolean 하나만 있으면 되고 pins/service.py::set_reaction이 이미
    pg_insert(...).on_conflict_do_update를 쓰는 선례가 있다(마이너 스킬 디테일)."""
    invite_row = db.execute(select(InviteRow).where(InviteRow.token == token)).scalar_one_or_none()
    if invite_row is None:
        raise AppError("UNAUTHORIZED", "초대 링크가 유효하지 않거나 만료되었습니다")

    now = datetime.now(timezone.utc)
    core.check_invite_acceptable(invite_row.expires_at, now)

    stmt = (
        pg_insert(MembershipRow)
        .values(map_id=invite_row.map_id, user_id=user_id, role="member")
        .on_conflict_do_nothing(index_elements=["map_id", "user_id"])
    )
    result = db.execute(stmt)
    created = result.rowcount == 1

    if created:
        db.execute(
            update(InviteRow)
            .where(InviteRow.token == token)
            .values(used_count=InviteRow.used_count + 1)
        )
        member = core.to_member_response(user_id, display_name=None, online=None)
        record_event(db, core.member_joined_event(invite_row.map_id, member))

    map_row = get_map_or_404(db, invite_row.map_id)
    return _map_response(db, map_row)


def list_members(db: Session, *, map_id: str) -> list[Member]:
    rows = db.execute(
        select(MembershipRow).where(MembershipRow.map_id == map_id).order_by(MembershipRow.joined_at)
    ).scalars().all()
    return [core.to_member_response(row.user_id, display_name=None, online=None) for row in rows]
