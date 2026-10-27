"""
다른 모듈이 maps를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). authz.ports.MembershipGateway 구현체와 구성원 수, 탈퇴 위임 함수가 있다.

authz/deps.py::get_membership_gateway가 이 클래스를 직접 쓴다(#89로 AllowAllMembership
스텁과 MEMBERSHIP_MODE 포트 자체가 제거됨, 배선은 루트가 적용) — 비구성원은 이제 실제로
404를 받는다. 이 모듈 자신의 테스트에서도 dependency_overrides로 이 클래스를 직접 꽂아
비구성원 404가 실제로 걸리는지 검증한다.

삭제된 지도(#369)는 이 게이트웨이에서 "구성원 없음"으로 답한다 — authz guard를 거치는 모든 지도
하위 경로(핀·추천·확정 리스트·SSE 구독)가 따로 고치지 않아도 404가 된다.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from authz.policy import Role
from maps import service
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow
from maps.schemas import Map


class DbMembershipGateway:
    """authz.ports.MembershipGateway를 구조적으로 만족한다(Protocol이라 상속 선언 불필요)."""

    def __init__(self, db: Session):
        self._db = db

    def get_role(self, map_id: str, user_id: str) -> Role | None:
        return self._db.execute(
            select(MembershipRow.role)
            .join(MapRow, MapRow.id == MembershipRow.map_id)
            .where(
                MembershipRow.map_id == map_id,
                MembershipRow.user_id == user_id,
                MapRow.deleted_at.is_(None),
            )
        ).scalar_one_or_none()

    def current_member_ids(self, map_id: str) -> set[str]:
        """지도의 현재 구성원 user_id 전부를 한 번에(#369). 핀 작성자 표시("나간 구성원")가 핀마다
        조회하지 않게 한다. 탈퇴자도 멤버십 행이 남아 있어 포함된다(#245) — 탈퇴 판정은 호출부가
        먼저 한다. 삭제된 지도는 빈 집합."""
        return set(self._db.execute(
            select(MembershipRow.user_id)
            .join(MapRow, MapRow.id == MembershipRow.map_id)
            .where(MembershipRow.map_id == map_id, MapRow.deleted_at.is_(None))
        ).scalars().all())


def count_members(db: Session, map_id: str) -> int:
    """이 지도에 현재 참여 중인 인원 수(Map.member_count, FilterCounts.members_total). 추천 준비 판정은
    더 이상 쓰지 않는다(#360 — 의견 핀 1곳이면 열린다). 탈퇴한 구성원은 뺀다(#245).
    나간 구성원은 멤버십 행이 지워져 자연히 빠진다(#369)."""
    return service.member_count(db, map_id)


def get_map_title(db: Session, map_id: str) -> str | None:
    """지도 제목(없거나 삭제된 지도는 None). 읽기 전용 — 알림 문장·확정 리스트 내보내기 파일명이 쓴다."""
    return service.get_map_title(db, map_id=map_id)


def get_map_region_label(db: Session, map_id: str) -> str | None:
    """지도의 지역 이름(지도 만들기의 지역 검색 결과 label, #22). 지역을 안 정했거나 없거나 삭제된 지도는 None. 읽기 전용 —
    recommend의 카카오맵 검색어가 핀 주소에서 동네를 못 찾았을 때 쓴다(#800)."""
    return db.execute(
        select(MapRow.region_label).where(MapRow.id == map_id, MapRow.deleted_at.is_(None))
    ).scalar_one_or_none()


def get_map_for_agent(db: Session, map_id: str) -> dict | None:
    """agent 스냅샷(docs/agent-v2.md 12.7, #522)이 부른다. 읽기 전용, 커밋하지 않는다.
    `{map_id, start_date, end_date, deleted: bool, members: [{user_id, joined_at}]}`. 구성원은 지금 구성원만
    (탈퇴자 제외, `count_members`와 같은 기준), joined_at 순. 지도가 없으면 None, 삭제된 지도는 deleted=True에
    members 빈 목록."""
    return service.get_map_for_agent(db, map_id=map_id)


def lock_member_maps(db: Session, user_id: str) -> list[str]:
    """탈퇴(auth.service.withdraw_user)가 맨 먼저 부른다(#435, docs/architecture.md "동시성: 지도 행
    잠금으로 줄을 세운다"). 이 사용자가 속한 삭제되지 않은 지도 행을 지도 id 순서로 FOR UPDATE 잠그고
    그 id를 돌려준다. 나가기·지도 삭제와 같은 행을 잠가 줄을 선다. 커밋하지 않는다."""
    return service.lock_member_maps(db, user_id=user_id)


def lock_map_if_alive(db: Session, map_id: str) -> bool:
    """agent가 모델 호출 뒤 저장 트랜잭션 맨 앞에서 부른다(docs/agent-v2.md 12.4, #512). 지도 행을 FOR UPDATE로
    잠그고(lock_member_maps와 같은 방식, docs/architecture.md "동시성: 지도 행 잠금으로 줄을 세운다", #435)
    삭제되지 않았으면 True. 삭제된 지도와 없는 지도는 False — 호출부는 아무것도 쓰지 않는다. 커밋하지 않는다."""
    return service.lock_map_if_alive(db, map_id=map_id)


def transfer_or_delete_owned_maps(db: Session, user_id: str) -> None:
    """탈퇴(auth.service.withdraw_user)가 부른다(#369 10번). 이 사용자가 방장인 지도마다
    joined_at이 가장 빠른 구성원(탈퇴자 제외)에게 방장을 넘기고, 넘길 사람이 없으면 지도를
    삭제한다(map.deleted 발행). 위임한 지도에는 member.left를 발행한다(new_owner_user_id=후임).
    탈퇴자의 멤버십 행은 지우지 않는다(#245). 커밋하지 않는다."""
    service.transfer_or_delete_owned_maps(db, user_id=user_id)


def purge_map_data(db: Session, *, map_ids: list[str]) -> dict[str, int]:
    """지도 정리(maps.purge, #431) — 이 지도들의 invites·memberships·maps만 지우고 테이블 이름 → 지운 행 수를
    돌려준다. 삭제되지 않은(deleted_at이 없는) 지도가 섞여 있으면 ValueError. 커밋하지 않는다."""
    return service.purge_map_data(db, map_ids=map_ids)


def check_invite(db: Session, token: str) -> None:
    """초대 토큰이 지금 수락 가능한지만 확인한다(#472, auth가 추가한 위임) — 없거나 삭제된 지도의 토큰은 404
    INVITE_NOT_FOUND, 끈 링크는 410 INVITE_REVOKED, 만료는 410 INVITE_EXPIRED. 쓰기 없음. 게스트 계정을 만들기
    전에 부른다(GUEST_LIMIT 409보다 이 404·410이 먼저)."""
    service._acceptable_invite_or_raise(db, token)


def accept_invite(db: Session, *, token: str, user_id: str) -> Map:
    """POST /invites/{token}/accept와 같은 흐름(#472, auth가 추가한 위임) — 구성원 가입, used_count, member.joined
    이벤트, 방장 알림까지 한 트랜잭션. 커밋은 호출자가 한다."""
    return service.accept_invite(db, token=token, user_id=user_id)


def purge_deleted_maps(db: Session, *, now: datetime, older_than_days: int) -> dict[str, int]:
    """정기 정리(#168)가 부른다 — 삭제한 지 `older_than_days`일이 지난 지도와 딸린 데이터를 지운다(`maps.purge`의 로직).
    테이블 이름 → 지운 행 수, 지운 지도 수는 `maps` 키가 아니라 `deleted_maps`에 담는다. 커밋은 호출자."""
    from maps import purge   # 지연 import — purge가 maps.api를 import해 순환이 된다

    map_count, counts = purge.purge(db, now=now, older_than_days=older_than_days)
    return {"deleted_maps": map_count, **counts}


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    """게스트 합치기(#560, auth가 부른다) — from_user의 멤버십·초대 발급자를 to_user로 옮긴다. 같은 지도에 to_user가
    이미 구성원이면 from_user 쪽만 지운다. 지도 수 상한은 보지 않는다. 멱등, 커밋은 호출자.
    키: memberships(옮김)·memberships_dropped(충돌로 지움)·invites."""
    return service.reassign_user(db, from_user_id=from_user_id, to_user_id=to_user_id)
