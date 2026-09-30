"""PlaceSource 계약과 소스 공통 값. 여기는 순수 — 네트워크를 모른다."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, replace
from typing import Any, Protocol, runtime_checkable

CATEGORIES = ("음식점", "카페", "숙소", "관광지", "기타")

# 층2 원자료 중 소스가 채워줄 수 있는 필드 묶음. 값이 None이면 "아직 못 채운 것"이다.
# rating은 rating_count와 한 묶음이다(같이 오고 같이 없다).
ENRICHABLE_FIELDS = frozenset({"phone", "rating", "price_level", "opening_hours"})


@dataclass(frozen=True)
class RawPlace:
    source: str
    source_id: str
    name: str
    lat: float
    lng: float
    category: str = "기타"
    address: str | None = None
    place_url: str | None = None
    phone: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    price_level: str | None = None       # 구글 priceLevel 열거값(예: "MODERATE"). 가격 숫자가 아니다.
    opening_hours: tuple[str, ...] | None = None
    contributed_by: tuple[str, ...] = ()  # 이 값에 필드를 채운 소스들(원 소스가 첫째)

    @property
    def place_id(self) -> str:
        return f"{self.source}:{self.source_id}"

    def missing(self) -> frozenset[str]:
        """아직 비어 있는 ENRICHABLE 필드."""
        empty = {
            "phone": not self.phone,
            "rating": self.rating is None,
            "price_level": self.price_level is None,
            "opening_hours": not self.opening_hours,
        }
        return frozenset(k for k, v in empty.items() if v)

    def merged(self, fields: dict[str, Any], by: str, wanted: frozenset[str]) -> RawPlace:
        """wanted 안에서, 아직 비어 있는 필드만 채운다 — 이미 채워진 값은 덮어쓰지 않는다."""
        allowed = {"phone": ("phone",), "rating": ("rating", "rating_count"),
                   "price_level": ("price_level",), "opening_hours": ("opening_hours",)}
        updates: dict[str, Any] = {}
        for group in wanted & self.missing():
            for attr in allowed[group]:
                if fields.get(attr) not in (None, "", ()):
                    updates[attr] = fields[attr]
        if not updates:
            return self
        return replace(self, **updates, contributed_by=self.contributed_by + (by,))


class PlaceSource(Protocol):
    name: str
    provides: frozenset[str]   # fill()이 채울 수 있는 ENRICHABLE 필드

    def is_configured(self) -> bool: ...

    def search_nearby(self, *, category: str, lat: float, lng: float, radius_m: int) -> list[RawPlace]: ...

    def fill(self, place: RawPlace, wanted: frozenset[str]) -> dict[str, Any]:
        """place와 같은 장소를 이 소스에서 찾아 wanted 필드 값만 돌려준다. 못 찾으면 {}."""
        ...


@runtime_checkable
class NameSearchable(Protocol):
    """이름 검색을 지원하는 소스(#180). 지금은 카카오만 — 네이버·구글은 켤 때 구현한다."""

    name: str

    def is_configured(self) -> bool: ...

    def search_by_name(self, *, query: str, lat: float | None, lng: float | None, limit: int) -> list[RawPlace]: ...


def synthetic_id(name: str, lat: float, lng: float) -> str:
    """id를 안 주는 소스(네이버)용 — 이름+좌표에서 결정적으로 만든다."""
    raw = f"{normalize_name(name)}@{lat:.5f},{lng:.5f}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def normalize_name(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def distance_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def is_same_place(a_name: str, a_lat: float, a_lng: float, b: RawPlace, max_dist_m: float = 200.0) -> bool:
    """이름이 같거나 한쪽이 다른 쪽을 포함하고, 가까울 때 같은 장소로 본다."""
    na, nb = normalize_name(a_name), normalize_name(b.name)
    if not na or not nb:
        return False
    if not (na == nb or na in nb or nb in na):
        return False
    return distance_m(a_lat, a_lng, b.lat, b.lng) <= max_dist_m
