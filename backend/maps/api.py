"""
다른 모듈이 maps를 부르는 유일한 접점(docs/architecture.md §1.1 "교차 모듈 쓰기는
<module>/api.py를 통해서만"). 지금은 authz.ports.MembershipGateway 구현체 하나뿐이다.

authz/deps.py는 여기서 건드리지 않는다 — 지금은 AllowAllMembership(모두 'member' 취급)
스텁이 걸려 있어 로그인한 누구나 모든 지도를 볼 수 있는 상태다. 이 파일이 그 스텁을
대체할 실구현을 내놓고, 실제 배선(authz/deps.py의 select() 호출 교체 + .env의
MEMBERSHIP_MODE=real)은 diff를 maps/for_Root.md에 적어 루트가 적용한다 — authz는 다른
세션이 담당하는 디렉토리라 그 파일을 직접 고치지 않는다. 이 모듈 자신의 테스트에서는
dependency_overrides로 이 클래스를 직접 꽂아 비구성원 404가 실제로 걸리는지 검증한다.
"""

from sqlalchemy import select
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
