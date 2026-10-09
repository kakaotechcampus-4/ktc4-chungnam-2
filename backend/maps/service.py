"""
얇은 I/O 셸 — 입력 수집 → core 호출 → DB 반영/응답 변환만 한다(docs/code-quality.md).
분기·계산 로직은 maps/core.py로 위임한다. 커밋하지 않는다 — common.database.get_db가
요청당 한 번 커밋하는 유일한 지점이다(db.flush()만 쓴다).
"""

import secrets
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from auth import api as auth_api
from authz.core import Principal
from common.errors import AppError
from common.events import record_event
from maps import core
from maps.models import Invite as InviteRow
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow
from maps.schemas import Invite, InviteSummary, Map, MapCreateRequest, Member
from pins import api as pins_api
from shortlist import api as shortlist_api

INVITE_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) — 256비트, 소지자가 곧 가입 권한을 갖는
# bearer capability라 uuid4가 아니라 secrets 모듈을 쓴다(예측 불가능성이 목적, 유일성이 아니다).

Rosters = dict[str, list[core.MembershipEntry]]


def _rosters(db: Session, map_ids: list[str]) -> tuple[Rosters, set[str]]:
    """지도별 멤버십 행과 그중 탈퇴자 집합. 구성원 수·요청자 역할·후임 판정이 모두 이 결과를 쓴다.
    GET /maps 목록용 배치이기도 하다 — N개 지도에 N번 쿼리하지 않는다(memberships 한 번 +
    auth.api.withdrawn_user_ids 한 번). map_ids가 비어 있으면 쿼리 자체를 건너뛴다."""
    if not map_ids:
        return {}, set()
    rows = db.execute(
        select(
            MembershipRow.id, MembershipRow.map_id, MembershipRow.user_id,
            MembershipRow.role, MembershipRow.joined_at,
        ).where(MembershipRow.map_id.in_(map_ids))
    ).all()
    withdrawn = auth_api.withdrawn_user_ids(db, list({row.user_id for row in rows}))
    rosters: Rosters = {map_id: [] for map_id in map_ids}
    for row in rows:
        rosters[row.map_id].append(core.MembershipEntry(
            id=row.id, user_id=row.user_id, role=row.role, joined_at=row.joined_at,
        ))
    return rosters, withdrawn


def _active_count(roster: list[core.MembershipEntry], withdrawn: set[str]) -> int:
    """탈퇴하지 않은 구성원 수(#245) — Map.member_count와 recommend 준비 판정 N이 쓴다.
    구성원 목록(list_members)은 핀 작성자 표기용으로 탈퇴자를 남기지만(#155) 수에서는 뺀다."""
    return sum(1 for m in roster if m.user_id not in withdrawn)


def _pin_counts(db: Session, map_ids: list[str]) -> dict[str, int]:
    """핀은 pins 소유 — pins.api가 id 목록을 한 번에 센다(지도 목록 N+1 방지, #313)."""
    return pins_api.count_public_pins_by_map(db, map_ids)


def member_count(db: Session, map_id: str) -> int:
    rosters, withdrawn = _rosters(db, [map_id])
    return _active_count(rosters[map_id], withdrawn)


def _region_lat_lng_columns():
    """geom::geometry 캐스트 후 ST_X/ST_Y로 좌표를 뽑는다(pins/service.py::_lat_lng_columns와
    동일 패턴 — geography 컬럼엔 ST_X/ST_Y가 직접 안 먹는다). region_center가 NULL이면
    ST_X/ST_Y도 NULL을 돌려주므로 region 없는 지도도 그대로 섞어 쿼리할 수 있다."""
    geom_as_geometry = cast(MapRow.region_center, Geometry())
    return func.ST_Y(geom_as_geometry).label("region_lat"), func.ST_X(geom_as_geometry).label("region_lng")


def get_map_or_404(db: Session, map_id: str, *, for_update: bool = False) -> MapRow:
    """삭제된 지도(#369)는 없는 지도와 같다 — 삭제 필터는 여기와 api.DbMembershipGateway에 모은다.
    for_update=True면 maps 행을 잠근다. 같은 지도의 나가기·삭제·탈퇴 위임이 이 잠금으로 줄을 선다
    (#369 13번 — 방장과 다음 사람이 동시에 나가 이미 나간 사람에게 방장이 넘어가는 걸 막는다)."""
    stmt = select(MapRow).where(MapRow.id == map_id, MapRow.deleted_at.is_(None))
    if for_update:
        stmt = stmt.with_for_update()
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise AppError("NOT_FOUND")
    return row


def _map_record(db: Session, map_row: MapRow) -> core.MapRecord:
    lat_col, lng_col = _region_lat_lng_columns()
    region_lat, region_lng = db.execute(
        select(lat_col, lng_col).where(MapRow.id == map_row.id)
    ).one()
    return core.MapRecord(
        id=map_row.id, title=map_row.title, start_date=map_row.start_date, end_date=map_row.end_date,
        created_by=map_row.created_by,
        region_label=map_row.region_label, region_lat=region_lat, region_lng=region_lng,
    )


def _map_response(db: Session, map_row: MapRow, *, viewer_id: str, with_next_owner: bool = False) -> Map:
    """permissions는 요청자 기준이라 viewer_id가 필요하다(#369). next_owner는 상세에서만 채운다."""
    rosters, withdrawn = _rosters(db, [map_row.id])
    roster = rosters[map_row.id]
    principal = Principal(user_id=viewer_id, map_id=map_row.id, role=core.role_in(roster, viewer_id))
    successor = core.owner_successor(principal, roster, withdrawn)
    next_owner = None
    if with_next_owner and successor is not None:
        successor_name = auth_api.display_names(db, [successor]).get(successor)
        next_owner = core.to_next_owner(principal, successor, successor_name)
    return core.to_map_response(
        _map_record(db, map_row),
        member_count=_active_count(roster, withdrawn),
        pin_count=_pin_counts(db, [map_row.id])[map_row.id],
        confirmed_count=shortlist_api.count_confirmed(db, map_id=map_row.id),
        permissions=core.map_permissions(principal, successor),
        my_role=principal.role,
        viewer_id=viewer_id,
        next_owner=next_owner,
    )


def _my_map_count(db: Session, user_id: str) -> int:
    """내 지도 수 — list_maps와 같은 기준(내 멤버십이 있고 삭제되지 않은 지도). 나간 지도는 행이 없어 안 센다."""
    return db.execute(
        select(func.count())
        .select_from(MembershipRow)
        .join(MapRow, MapRow.id == MembershipRow.map_id)
        .where(MembershipRow.user_id == user_id, MapRow.deleted_at.is_(None))
    ).scalar_one()


def create_map(db: Session, *, req: MapCreateRequest, creator_id: str) -> Map:
    """maps 행 + owner 멤버십 행을 같은 트랜잭션에 만든다. 멤버십이 빠지면 생성자가 자기
    지도의 비구성원이 되어 이후 모든 요청이 404가 된다 — 테스트가 DB를 직접 확인한다.

    seeding 프리시딩 잡을 여기서 큐잉하지 않는다: architecture.md 3절은 그 잡의 지역을
    "첫 핀 좌표로 확정"한다고 정의하는데, 이 시점엔 핀이 0개라 region을 채울 방법이 없다
    (maps/CLAUDE.md 완료 정의와의 모순 — maps/for_Root.md 항목 2로 보고). 로그만 찍는 no-op
    훅은 완료 정의 체크박스만 채우는 가짜 구현이라 만들지 않는다."""
    new_map = core.validate_map_create(req.title, req.start_date, req.end_date, req.region)
    core.check_map_limit(_my_map_count(db, creator_id))

    map_row = MapRow(
        title=new_map.title, start_date=new_map.start_date, end_date=new_map.end_date,
        created_by=creator_id,
        region_label=new_map.region.label if new_map.region else None,
        region_center=(
            func.ST_SetSRID(func.ST_MakePoint(new_map.region.lng, new_map.region.lat), 4326)
            if new_map.region else None
        ),
    )
    db.add(map_row)
    db.flush()  # map_row.id 확정 — 멤버십 행이 참조해야 한다

    db.add(MembershipRow(map_id=map_row.id, user_id=creator_id, role="owner"))
    db.flush()

    return _map_response(db, map_row, viewer_id=creator_id)


def get_map_response(db: Session, *, map_id: str, viewer_id: str) -> Map:
    map_row = get_map_or_404(db, map_id)
    return _map_response(db, map_row, viewer_id=viewer_id, with_next_owner=True)


def list_maps(db: Session, *, user_id: str) -> list[Map]:
    """내가 구성원인 지도, 최근 생성순(#24, docs/CHANGELOG-api.md 2026-09-28). 삭제된 지도는 빼고,
    내가 나간 지도는 멤버십 행이 없어 애초에 안 잡힌다(#369). 특정 mapId를 전제하는
    require_map_member()류 가드를 못 쓴다 — memberships를 user_id로 조인하는 전용 쿼리다.

    member_count·permissions는 지도별로 따로 쿼리하지 않는다 — _rosters가 이번 결과에 나온
    map_id 전체를 한 번에 읽는다. region_lat/region_lng도 이 목록 쿼리 자체의
    SELECT 절에 포함시켜서(join이 아니라 같은 행의 계산 컬럼) 지도당 추가 쿼리가 없다.
    confirmed_count는 shortlist_api.count_confirmed에 배치 버전이 없어 지도당 한 번씩
    호출한다 — 이 모듈이 shortlist/api.py를 소유하지 않아 여기서 배치화할 수 없다(maps/for_Root.md
    보고 대상). next_owner는 목록에서 채우지 않는다(스펙)."""
    lat_col, lng_col = _region_lat_lng_columns()
    rows = db.execute(
        select(MapRow, lat_col, lng_col)
        .join(MembershipRow, MembershipRow.map_id == MapRow.id)
        .where(MembershipRow.user_id == user_id, MapRow.deleted_at.is_(None))
        .order_by(MapRow.created_at.desc())
    ).all()
    if not rows:
        return []

    map_ids = [map_row.id for map_row, _, _ in rows]
    rosters, withdrawn = _rosters(db, map_ids)
    pin_counts = _pin_counts(db, map_ids)
    responses = []
    for map_row, region_lat, region_lng in rows:
        roster = rosters[map_row.id]
        principal = Principal(user_id=user_id, map_id=map_row.id, role=core.role_in(roster, user_id))
        successor = core.owner_successor(principal, roster, withdrawn)
        responses.append(core.to_map_response(
            core.MapRecord(
                id=map_row.id, title=map_row.title, start_date=map_row.start_date,
                end_date=map_row.end_date, created_by=map_row.created_by,
                region_label=map_row.region_label, region_lat=region_lat, region_lng=region_lng,
            ),
            member_count=_active_count(roster, withdrawn),
            pin_count=pin_counts[map_row.id],
            confirmed_count=shortlist_api.count_confirmed(db, map_id=map_row.id),
            permissions=core.map_permissions(principal, successor),
            my_role=principal.role,
            viewer_id=user_id,
        ))
    return responses


def create_invite(db: Session, *, map_id: str, creator_id: str, base_url: str) -> Invite:
    """base_url은 router가 만든 값을 그대로 받는다 — settings.frontend_base_url이 있으면
    그 값(FE 오리진, 루트 확정 2026-09-23 — maps/for_Root.md 항목 6 해결), 없으면 예전처럼
    request.base_url(백엔드 자신의 주소). 결과 URL은 `/invites/{token}` 경로를 프론트의
    "초대 수락 화면"(#4 잔여 항목)이 받아서 POST /invites/{token}/accept를 호출하는 걸
    전제로 한다."""
    token = secrets.token_urlsafe(INVITE_TOKEN_BYTES)
    now = datetime.now(timezone.utc)
    expires_at = core.invite_expires_at(now)

    invite_row = InviteRow(token=token, map_id=map_id, created_by=creator_id, expires_at=expires_at)
    db.add(invite_row)
    db.flush()

    return Invite(token=token, url=core.build_invite_url(base_url, token), expires_at=expires_at)


def _acceptable_invite_or_raise(db: Session, token: str) -> InviteRow:
    """없으면 404 INVITE_NOT_FOUND, 만료면 410 INVITE_EXPIRED — 조회와 수락이 공유한다.
    삭제된 지도(#369)의 토큰은 없는 토큰과 같다 — 만료 여부보다 먼저 404다."""
    invite_row = db.execute(
        select(InviteRow)
        .join(MapRow, MapRow.id == InviteRow.map_id)
        .where(InviteRow.token == token, MapRow.deleted_at.is_(None))
    ).scalar_one_or_none()
    if invite_row is None:
        raise AppError("INVITE_NOT_FOUND")
    core.check_invite_acceptable(invite_row.expires_at, datetime.now(timezone.utc))
    return invite_row


def get_invite_summary(db: Session, *, token: str) -> InviteSummary:
    """로그인 없이 호출된다(#23) — 토큰이 곧 접근 권한이라 제목·기간·구성원 수·초대자 이름만
    돌려준다. 쓰기 없음(used_count도 안 올린다)."""
    invite_row = _acceptable_invite_or_raise(db, token)
    map_row = get_map_or_404(db, invite_row.map_id)
    inviter_name = auth_api.display_names(db, [invite_row.created_by]).get(invite_row.created_by)
    return core.to_invite_summary(
        _map_record(db, map_row),
        member_count=member_count(db, map_row.id),
        pin_count=_pin_counts(db, [map_row.id])[map_row.id],
        inviter_display_name=inviter_name,
        expires_at=invite_row.expires_at,
    )


def accept_invite(db: Session, *, token: str, user_id: str) -> Map:
    """순서가 핵심이다 — 존재·만료 확인 → 멤버십 upsert → used_count/이벤트(실제 가입 시에만).
    ON CONFLICT DO NOTHING을 쓴다(DO UPDATE 아님) — owner가 자기 초대를 열어도 role이
    조용히 'member'로 강등되지 않는다. shortlist/service.py::add_item의 savepoint+rollback
    패턴을 여기선 쓰지 않는다 — 그 패턴의 db.rollback()은 같은 요청의 앞선 쓰기를 전부
    날리는데, 여기선 boolean 하나만 있으면 되고 pins/service.py::set_reaction이 이미
    pg_insert(...).on_conflict_do_update를 쓰는 선례가 있다(마이너 스킬 디테일)."""
    invite_row = _acceptable_invite_or_raise(db, token)
    already_member = db.execute(
        select(MembershipRow.id).where(MembershipRow.map_id == invite_row.map_id, MembershipRow.user_id == user_id)
    ).first() is not None
    if not already_member:
        # 이미 구성원인 지도의 재수락은 새 참여가 아니라 막지 않는다(#369 15번).
        core.check_map_limit(_my_map_count(db, user_id))

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
        name = auth_api.display_names(db, [user_id]).get(user_id)

    map_row = get_map_or_404(db, invite_row.map_id)
    if created:
        # 방금 넣은 행은 언제나 member다(위 insert). maps.created_by로 판정하지 않는다(#369 11번).
        member = core.to_member_response(user_id, role="member", display_name=name, online=None)
        record_event(db, core.member_joined_event(invite_row.map_id, member))
    return _map_response(db, map_row, viewer_id=user_id)


def list_members(db: Session, *, map_id: str) -> list[Member]:
    """role은 memberships.role 그대로다(#369 11번) — 위임되면 새 방장이 owner로 보인다."""
    get_map_or_404(db, map_id)
    rows = db.execute(
        select(MembershipRow).where(MembershipRow.map_id == map_id).order_by(MembershipRow.joined_at)
    ).scalars().all()
    # 배치 조회 — N명에 N번 쿼리하지 않는다(auth.api.display_names 자체가 배치용으로 설계됨).
    names = auth_api.display_names(db, [row.user_id for row in rows])
    return [
        core.to_member_response(
            row.user_id, role=row.role, display_name=names.get(row.user_id), online=None
        )
        for row in rows
    ]


def delete_map(db: Session, *, map_id: str) -> None:
    """soft delete(#369 5번). 방장인지는 라우터의 require_on_map("map.delete")가 이미 봤다.
    map.deleted는 같은 트랜잭션에 기록한다 — 커밋되면 삭제와 이벤트가 함께 보인다."""
    map_row = get_map_or_404(db, map_id, for_update=True)
    map_row.deleted_at = datetime.now(timezone.utc)
    db.flush()
    record_event(db, core.map_deleted_event(map_id))


def roster_of(db: Session, map_id: str) -> tuple[list[core.MembershipEntry], set[str]]:
    """한 지도의 멤버십과 탈퇴자 집합 — 나가기·탈퇴 위임이 후임을 정할 때 쓴다."""
    rosters, withdrawn = _rosters(db, [map_id])
    return rosters[map_id], withdrawn


def transfer_owner(db: Session, *, map_id: str, from_user_id: str, to_user_id: str) -> None:
    """강등 먼저, 승격 나중(#369 12번). uq_memberships_one_owner_per_map은 문장마다 검사돼서
    순서가 바뀌면 그 사이 방장이 2명이 되어 실패한다."""
    db.execute(
        update(MembershipRow)
        .where(MembershipRow.map_id == map_id, MembershipRow.user_id == from_user_id)
        .values(role="member")
    )
    db.execute(
        update(MembershipRow)
        .where(MembershipRow.map_id == map_id, MembershipRow.user_id == to_user_id)
        .values(role="owner")
    )


def remove_membership(db: Session, *, map_id: str, user_id: str) -> None:
    """나가기는 행을 지운다(#369 7번). 다시 수락하면 새 행·새 joined_at으로 순서 맨 뒤에 선다."""
    db.execute(
        delete(MembershipRow).where(MembershipRow.map_id == map_id, MembershipRow.user_id == user_id)
    )


def _owned_map_ids(db: Session, *, user_id: str) -> list[str]:
    """이 사용자가 방장인 삭제되지 않은 지도. id 순 — 여러 지도를 차례로 잠글 때 순서를 고정해
    교착을 피한다."""
    return list(db.execute(
        select(MapRow.id)
        .join(MembershipRow, MembershipRow.map_id == MapRow.id)
        .where(
            MembershipRow.user_id == user_id, MembershipRow.role == "owner", MapRow.deleted_at.is_(None)
        )
        .order_by(MapRow.id)
    ).scalars().all())


def lock_member_maps(db: Session, *, user_id: str) -> list[str]:
    """이 사용자가 속한 삭제되지 않은 지도 행을 지도 id 순서로 FOR UPDATE 잠근다(#435). 방장이 아니어도
    잠근다 — 탈퇴가 이 사람의 모든 지도에서 나가기와 줄을 서야 하기 때문이다. 순서를 고정해
    서로 기다리다 멈추는 교착을 피한다. 잠근 지도 id를 돌려준다. 커밋하지 않는다(잠금은 트랜잭션 끝까지)."""
    return list(db.execute(
        select(MapRow.id)
        .where(
            MapRow.id.in_(select(MembershipRow.map_id).where(MembershipRow.user_id == user_id)),
            MapRow.deleted_at.is_(None),
        )
        .order_by(MapRow.id)
        .with_for_update()
    ).scalars().all())


def transfer_or_delete_owned_maps(db: Session, *, user_id: str) -> None:
    """탈퇴(#369 10번) — 방장인 지도마다 후임에게 넘기고, 넘길 사람이 없으면 지도를 삭제한다.
    탈퇴자의 멤버십 행은 핀 작성자 표시용으로 남긴다(#245) — 강등만 하고 지우지 않는다.
    위임한 지도에는 member.left(user_id=탈퇴자, new_owner_user_id=후임)를, 삭제한 지도에는 map.deleted만
    남긴다(docs/events.md, 2026-10-07 결정)."""
    for map_id in _owned_map_ids(db, user_id=user_id):
        get_map_or_404(db, map_id, for_update=True)
        roster, withdrawn = roster_of(db, map_id)
        if core.role_in(roster, user_id) != "owner":
            continue  # 잠그기 전에 다른 요청이 이미 넘겼다
        successor = core.pick_successor(roster, withdrawn, user_id)
        if successor is None:
            delete_map(db, map_id=map_id)
        else:
            transfer_owner(db, map_id=map_id, from_user_id=user_id, to_user_id=successor)
            record_event(db, core.member_left_event(map_id, user_id, successor))
