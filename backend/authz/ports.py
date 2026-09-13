"""
다른 모듈에 대한 이 모듈의 의존을 프로토콜로 좁혀둔다(backend/pins/ports.py와 같은 패턴).
docs/architecture.md 1절 "다른 모듈의 테이블을 직접 import·쿼리하지 않는다"를 지키기 위한
최소 접점 — memberships는 maps(#19) 소유라 authz가 직접 쿼리하지 않는다.

maps(#19)가 실구현을 채울 때까지는 backend/authz/deps.py의 개발용 어댑터를 쓴다.
"""

from typing import Protocol

from authz.policy import Role


class MembershipGateway(Protocol):
    """구성원 역할 조회 인터페이스. maps(#19)가 실구현을 채운다.

    pins/ports.py의 MembershipGateway는 is_member(...) -> bool만 묻는다 — authz는 역할까지
    필요해서 get_role(...)로 이름을 다르게 뒀다. Protocol은 구조적 타이핑이라, maps(#19)가 두
    메서드(is_member·get_role)를 한 어댑터 클래스에 함께 두면 그 클래스 하나로 pins와 authz
    양쪽 Protocol을 동시에 만족시킬 수 있다 — 상속이나 등록이 필요 없다."""

    def get_role(self, map_id: str, user_id: str) -> Role | None: ...
