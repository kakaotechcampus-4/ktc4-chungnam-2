"""
얇은 I/O 셸 — 입력 수집 → core 호출 → DB 반영/응답 변환만 한다(docs/code-quality.md).
분기·계산 로직은 maps/core.py로 위임한다. 커밋하지 않는다 — common.database.get_db가
요청당 한 번 커밋하는 유일한 지점이다(db.flush()만 쓴다).
"""

import secrets
from datetime import datetime, timezone

from geoalchemy2 import Geometry
from sqlalchemy import cast, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from auth import api as auth_api
from common.errors import AppError
from common.events import record_event
from maps import core
from maps.models import Invite as InviteRow
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow
from maps.schemas import Invite, InviteSummary, Map, MapCreateRequest, Member
from shortlist import api as shortlist_api

INVITE_TOKEN_BYTES = 32  # secrets.token_urlsafe(32) — 256비트, 소지자가 곧 가입 권한을 갖는
# bearer capability라 uuid4가 아니라 secrets 모듈을 쓴다(예측 불가능성이 목적, 유일성이 아니다).


def _member_count(db: Session, map_id: str) -> int:
    return db.execute(
        select(func.count()).select_from(MembershipRow).where(MembershipRow.map_id == map_id)
    ).scalar_one()


def _member_counts(db: Session, map_ids: list[str]) -> dict[str, int]:
    """GET /maps 목록용 — N개 지도에 N번 쿼리하지 않는다(pins/for_Root.md·auth.api.display_names와
    같은 배치 원칙). map_ids가 비어 있으면 쿼리 자체를 건너뛴다."""
    if not map_ids:
        return {}
    rows = db.execute(
        select(MembershipRow.map_id, func.count())
        .where(MembershipRow.map_id.in_(map_ids))
        .group_by(MembershipRow.map_id)
    ).all()
    return {map_id: count for map_id, count in rows}


def _region_lat_lng_columns():
    """geom::geometry 캐스트 후 ST_X/ST_Y로 좌표를 뽑는다(pins/service.py::_lat_lng_columns와
    동일 패턴 — geography 컬럼엔 ST_X/ST_Y가 직접 안 먹는다). region_center가 NULL이면
    ST_X/ST_Y도 NULL을 돌려주므로 region 없는 지도도 그대로 섞어 쿼리할 수 있다."""
    geom_as_geometry = cast(MapRow.region_center, Geometry())
    return func.ST_Y(geom_as_geometry).label("region_lat"), func.ST_X(geom_as_geometry).label("region_lng")


def get_map_or_404(db: Session, map_id: str) -> MapRow:
    row = db.execute(select(MapRow).where(MapRow.id == map_id)).scalar_one_or_none()
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
        region_label=map_row.region_label, region_lat=region_lat, region_lng=region_lng,
    )


def _map_response(db: Session, map_row: MapRow) -> Map:
    return core.to_map_response(
        _map_record(db, map_row),
        member_count=_member_count(db, map_row.id),
        confirmed_count=shortlist_api.count_confirmed(db, map_id=map_row.id),
    )


def create_map(db: Session, *, req: MapCreateRequest, creator_id: str) -> Map:
    """maps 행 + owner 멤버십 행을 같은 트랜잭션에 만든다. 멤버십이 빠지면 생성자가 자기
    지도의 비구성원이 되어 이후 모든 요청이 404가 된다 — 테스트가 DB를 직접 확인한다.

    seeding 프리시딩 잡을 여기서 큐잉하지 않는다: architecture.md 3절은 그 잡의 지역을
    "첫 핀 좌표로 확정"한다고 정의하는데, 이 시점엔 핀이 0개라 region을 채울 방법이 없다
    (maps/CLAUDE.md 완료 정의와의 모순 — maps/for_Root.md 항목 2로 보고). 로그만 찍는 no-op
    훅은 완료 정의 체크박스만 채우는 가짜 구현이라 만들지 않는다."""
    new_map = core.validate_map_create(req.title, req.start_date, req.end_date, req.region)

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

    return _map_response(db, map_row)


def get_map_response(db: Session, *, map_id: str) -> Map:
    map_row = get_map_or_404(db, map_id)
    return _map_response(db, map_row)


def list_maps(db: Session, *, user_id: str) -> list[Map]:
    """내가 구성원인 지도, 최근 생성순(#24, docs/CHANGELOG-api.md 2026-09-28). 특정 mapId를
    전제하는 require_map_member()류 가드를 못 쓴다 — memberships를 user_id로 조인하는
    전용 쿼리다.

    member_count는 지도별로 따로 쿼리하지 않는다 — _member_counts가 이번 결과에 나온
    map_id 전체를 한 번의 GROUP BY로 집계한다. region_lat/region_lng도 이 목록 쿼리 자체의
    SELECT 절에 포함시켜서(join이 아니라 같은 행의 계산 컬럼) 지도당 추가 쿼리가 없다.
    confirmed_count는 shortlist_api.count_confirmed에 배치 버전이 없어 지도당 한 번씩
    호출한다 — 이 모듈이 shortlist/api.py를 소유하지 않아 여기서 배치화할 수 없다(maps/for_Root.md
    보고 대상)."""
    lat_col, lng_col = _region_lat_lng_columns()
    rows = db.execute(
        select(MapRow, lat_col, lng_col)
        .join(MembershipRow, MembershipRow.map_id == MapRow.id)
        .where(MembershipRow.user_id == user_id)
        .order_by(MapRow.created_at.desc())
    ).all()
    if not rows:
        return []

    counts = _member_counts(db, [map_row.id for map_row, _, _ in rows])
    return [
        core.to_map_response(
            core.MapRecord(
                id=map_row.id, title=map_row.title, start_date=map_row.start_date,
                end_date=map_row.end_date, region_label=map_row.region_label,
                region_lat=region_lat, region_lng=region_lng,
            ),
            member_count=counts.get(map_row.id, 0),
            confirmed_count=shortlist_api.count_confirmed(db, map_id=map_row.id),
        )
        for map_row, region_lat, region_lng in rows
    ]


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
    """없으면 404 INVITE_NOT_FOUND, 만료면 410 INVITE_EXPIRED — 조회와 수락이 공유한다."""
    invite_row = db.execute(select(InviteRow).where(InviteRow.token == token)).scalar_one_or_none()
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
        member_count=_member_count(db, map_row.id),
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
        member = core.to_member_response(user_id, display_name=name, online=None)
        record_event(db, core.member_joined_event(invite_row.map_id, member))

    map_row = get_map_or_404(db, invite_row.map_id)
    return _map_response(db, map_row)


def list_members(db: Session, *, map_id: str) -> list[Member]:
    rows = db.execute(
        select(MembershipRow).where(MembershipRow.map_id == map_id).order_by(MembershipRow.joined_at)
    ).scalars().all()
    # 배치 조회 — N명에 N번 쿼리하지 않는다(auth.api.display_names 자체가 배치용으로 설계됨).
    names = auth_api.display_names(db, [row.user_id for row in rows])
    return [core.to_member_response(row.user_id, display_name=names.get(row.user_id), online=None) for row in rows]
