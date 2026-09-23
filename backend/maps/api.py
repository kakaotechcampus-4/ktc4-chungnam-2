"""
다른 모듈이 maps를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). 지금은 authz.ports.MembershipGateway 구현체 하나뿐이다.

authz/deps.py::get_membership_gateway가 이 클래스를 직접 쓴다(#89로 AllowAllMembership
스텁과 MEMBERSHIP_MODE 포트 자체가 제거됨, 배선은 루트가 적용) — 비구성원은 이제 실제로
404를 받는다. 이 모듈 자신의 테스트에서도 dependency_overrides로 이 클래스를 직접 꽂아
비구성원 404가 실제로 걸리는지 검증한다.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from authz.policy import Role
from maps.models import Membership as MembershipRow


class DbMembershipGateway:
    """authz.ports.MembershipGateway를 구조적으로 만족한다(Protocol이라 상속 선언 불필요)."""

    def __init__(self, db: Session):
        self._db = db

    def get_role(self, map_id: str, user_id: str) -> Role | None:
        return self._db.execute(
            select(MembershipRow.role).where(
                MembershipRow.map_id == map_id, MembershipRow.user_id == user_id
            )
        ).scalar_one_or_none()


def count_members(db: Session, map_id: str) -> int:
    """recommend readiness(5-4)가 ceil(N/2)의 N으로 쓴다(recommend/#108). N="이 지도에
    현재 참여 중인 인원 수"로 확정(#32, 2026-09-23) — maps가 소유한 함수라 여기 추가했다
    (get_coordinates_for_pins를 pins가 shortlist를 위해 추가한 것과 같은 선례)."""
    return db.execute(
        select(func.count()).select_from(MembershipRow).where(MembershipRow.map_id == map_id)
    ).scalar_one()
