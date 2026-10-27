"""
다른 모듈에 대한 이 모듈의 의존을 프로토콜로 좁혀둔다.
docs/architecture.md 1절 "다른 모듈의 테이블을 직접 import·쿼리하지 않는다"를 지키기 위한
최소 접점 — memberships는 maps(#19) 소유라 authz가 직접 쿼리하지 않는다.

maps(#19)가 실구현을 채울 때까지는 backend/authz/deps.py의 개발용 어댑터를 쓴다.
"""

from typing import Protocol

from authz.policy import Role


class MembershipGateway(Protocol):
    """구성원 역할 조회 인터페이스. maps(#19)가 실구현을 채운다.

    실구현은 maps.api.DbMembershipGateway 하나이고, pins도 그것을 직접 쓴다(#89)."""

    def get_role(self, map_id: str, user_id: str) -> Role | None: ...
