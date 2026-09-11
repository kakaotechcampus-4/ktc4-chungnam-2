"""
backend/authz — 선언적 권한 판정 모듈의 공개 API.

다른 모듈은 이 패키지에서 직접 import해서 쓴다:
    from authz import can, permissions_for, Principal, Resource
    from authz.service import resolve_principal
    from authz.deps import MembershipGatewayDep, get_membership_gateway
    from authz.ports import MembershipGateway

authz/CLAUDE.md "넘지 말 것" — 다른 모듈은 여기 판정 함수를 거치지 않고 권한 if문을 직접
심지 않는다.
"""

from authz.core import Principal, Resource, can, permissions_for
from authz.policy import Role
from authz.schemas import Permissions

__all__ = [
    "can",
    "permissions_for",
    "Principal",
    "Resource",
    "Permissions",
    "Role",
]
