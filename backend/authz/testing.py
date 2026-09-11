"""pins/maps/shortlist가 각자 가짜 멤버십을 만들지 않게 한다 — guard.py와 같은 원칙
(관리 지점을 하나로)."""

from authz.policy import Role
from authz.ports import MembershipGateway


class FakeMembership(MembershipGateway):
    def __init__(self, roles: dict[tuple[str, str], Role | None]):
        self._roles = roles

    def get_role(self, map_id: str, user_id: str) -> Role | None:
        return self._roles.get((map_id, user_id))
