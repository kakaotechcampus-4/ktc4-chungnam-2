"""
다른 모듈에 대한 이 모듈의 의존을 프로토콜로 좁혀둔다.
docs/architecture.md 1절 "다른 모듈의 테이블을 직접 import·쿼리하지 않는다"와
docs/code-quality.md "의존성 화살표는 항상 안쪽을 향한다"를 지키기 위한 최소 접점.

실구현체는 각 모듈이 준비되는 대로 여기 Protocol에 맞춰 넣으면 되고, 그 전까지는
backend/pins/deps.py의 개발용 어댑터를 쓴다.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PinDraft:
    """핀 생성 요청에서 장소 조회에 필요한 부분만 추린 값."""

    source: str  # "link" | "search" | "coordinate"
    link_url: str | None
    place_id: str | None
    lat: float | None
    lng: float | None


@dataclass(frozen=True)
class ResolvedPlace:
    """장소 조회 결과 — pins 테이블에 실제로 쓰이는 값만 담는다."""

    place_id: str
    lat: float
    lng: float


class PlaceGateway(Protocol):
    """장소 조회 인터페이스. places(#34)가 실구현을 채운다."""

    def resolve(self, draft: PinDraft) -> ResolvedPlace: ...
