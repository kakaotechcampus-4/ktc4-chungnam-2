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

from sqlalchemy import select
from sqlalchemy.orm import Session

from authz.policy import Role
from maps import service
from maps.models import Map as MapRow
from maps.models import Membership as MembershipRow


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
    """recommend readiness(5-4)가 ceil(N/2)의 N으로 쓴다(recommend/#108). N="이 지도에
    현재 참여 중인 인원 수"로 확정(#32, 2026-09-23) — maps가 소유한 함수라 여기 추가했다
    (get_coordinates_for_pins를 pins가 shortlist를 위해 추가한 것과 같은 선례).
    탈퇴한 구성원은 센 N에서 뺀다(#245) — 반응할 수 없는 사람이 ceil(N/2)를 부풀리지 않게.
    나간 구성원은 멤버십 행이 지워져 자연히 빠진다(#369)."""
    return service.member_count(db, map_id)


def transfer_or_delete_owned_maps(db: Session, user_id: str) -> None:
    """탈퇴(auth.service.withdraw_user)가 부른다(#369 10번). 이 사용자가 방장인 지도마다
    joined_at이 가장 빠른 구성원(탈퇴자 제외)에게 방장을 넘기고, 넘길 사람이 없으면 지도를
    삭제한다(map.deleted 발행). 탈퇴자의 멤버십 행은 지우지 않는다(#245). 커밋하지 않는다."""
    service.transfer_or_delete_owned_maps(db, user_id=user_id)
