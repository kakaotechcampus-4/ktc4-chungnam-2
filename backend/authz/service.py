"""
얇은 I/O 셸 — 게이트웨이를 불러 역할을 조회하고 Principal로 조립하는 것 말고는 아무 것도
하지 않는다(docs/code-quality.md). 분기·계산 로직은 core.py에 있다.
"""

from authz.core import Principal
from authz.ports import MembershipGateway


def resolve_principal(gateway: MembershipGateway, map_id: str, user_id: str) -> Principal:
    """호출 모듈이 이미 가진 (map_id, user_id)로 이 지도에서의 역할을 조회해 Principal을 만든다.
    Principal.map_id를 여기서 못 박아두는 게 중요하다 — core.can()이 이 map_id와 resource.map_id를
    대조해서 교차 지도 오용을 막는다."""
    role = gateway.get_role(map_id, user_id)
    return Principal(user_id=user_id, map_id=map_id, role=role)
