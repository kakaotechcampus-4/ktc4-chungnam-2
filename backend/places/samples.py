"""PLACES_MODE=dev의 고정 샘플 5곳 — 카카오를 부르지 않고 FE·통합 테스트가 키 없이 돈다.
contracts/mocks/handlers/places.ts의 SEED_PLACES와 같은 장소다(바꾸면 둘 다 바꾼다). 실제 카카오 응답이 아니다."""

from __future__ import annotations

from places.sources.base import RawPlace, distance_m


def _p(n: int, name: str, lat: float, lng: float, category: str, address: str, with_url: bool) -> RawPlace:
    return RawPlace(source="kakao", source_id=f"mock-{n}", name=name, lat=lat, lng=lng, category=category,
                    address=address, place_url=f"https://place.map.kakao.com/mock-{n}" if with_url else None)


SAMPLE_PLACES: tuple[RawPlace, ...] = (
    _p(1, "해운대 밀면", 35.1631, 129.1639, "음식점", "부산 해운대구 우동", True),
    _p(2, "해운대 바다 카페", 35.1587, 129.1604, "카페", "부산 해운대구 중동", True),
    _p(3, "광안리 해변", 35.1532, 129.1186, "관광지", "부산 수영구 광안동", False),
    _p(4, "광안리 게스트하우스", 35.1547, 129.1191, "숙소", "부산 수영구 광안동", False),
    _p(5, "제주 흑돼지 거리", 33.5131, 126.5296, "음식점", "제주 제주시 일도이동", False),
)


def search_samples(query: str, lat: float | None, lng: float | None, limit: int) -> list[RawPlace]:
    found = [p for p in SAMPLE_PLACES if query in p.name]
    if lat is not None and lng is not None:
        found.sort(key=lambda p: distance_m(lat, lng, p.lat, p.lng))
    return found[:limit]
