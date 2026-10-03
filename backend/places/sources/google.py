"""Google Places API(New) — 3순위. 가격대·평점·영업시간을 주는 유일한 소스라 과금이 있다.
호출을 줄이는 세 장치: ① FieldMask에 필요한 것만, ② 재시도 없음, ③ 프로세스당 호출 상한.
priceRange(가격 숫자)는 요청하지 않는다 — priceLevel(열거값)만."""

from __future__ import annotations

import logging
from typing import Any

from places.http import CallStats, SourceError, SourceHttp
from places.sources.base import RawPlace, is_same_place

BASE = "https://places.googleapis.com/v1"
_TYPES = {"음식점": ["restaurant"], "카페": ["cafe"], "숙소": ["lodging"], "관광지": ["tourist_attraction"]}
_CATEGORY_OF_TYPE = (("cafe", "카페"), ("lodging", "숙소"), ("tourist_attraction", "관광지"), ("restaurant", "음식점"))
_MAX_RADIUS_M = 50000.0
# 매칭에 필요한 최소 필드 + wanted 그룹별 필드
_MATCH_MASK = ("places.id", "places.displayName", "places.location")
_FIELD_MASK = {
    "phone": ("places.nationalPhoneNumber",),
    "rating": ("places.rating", "places.userRatingCount"),
    "price_level": ("places.priceLevel",),
    "opening_hours": ("places.regularOpeningHours",),
}
_NEARBY_MASK = ("places.id", "places.displayName", "places.location", "places.formattedAddress",
                "places.types", "places.googleMapsUri")

log = logging.getLogger("pingo.places")


class GooglePlaceSource:
    name = "google"
    provides = frozenset(_FIELD_MASK)

    def __init__(self, http: SourceHttp, stats: CallStats, api_key: str, *, max_calls: int = 100) -> None:
        self._http = http
        self._stats = stats
        self._key = api_key
        self._max_calls = max_calls

    def is_configured(self) -> bool:
        return bool(self._key)

    def _post(self, endpoint: str, path: str, body: dict[str, Any], mask: tuple[str, ...]) -> dict[str, Any]:
        if self._max_calls and self._stats.count(self.name) >= self._max_calls:
            log.warning("places.google 호출 상한(%d) 도달 — 호출하지 않는다", self._max_calls)
            raise SourceError(f"google: 호출 상한 {self._max_calls} 도달")
        return self._http.request_json(
            self.name, endpoint, "POST", f"{BASE}/{path}",
            headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": ",".join(mask)},
            json=body, retries=0,   # 과금 호출이라 재시도하지 않는다
        )

    def search_nearby(self, *, category: str, lat: float, lng: float, radius_m: int) -> list[RawPlace]:
        types = _TYPES.get(category)
        if types is None:
            return []
        body = self._post("nearby", "places:searchNearby", {
            "includedTypes": types, "maxResultCount": 20, "languageCode": "ko", "rankPreference": "DISTANCE",
            "locationRestriction": {"circle": {"center": {"latitude": lat, "longitude": lng},
                                               "radius": min(float(radius_m), _MAX_RADIUS_M)}},
        }, _NEARBY_MASK)
        return [p for p in (_parse(d) for d in body.get("places", [])) if p]

    def fill(self, place: RawPlace, wanted: frozenset[str]) -> dict[str, Any]:
        groups = wanted & self.provides
        if not groups:
            return {}
        mask = _MATCH_MASK + tuple(f for g in sorted(groups) for f in _FIELD_MASK[g])
        body = self._post("text", "places:searchText", {
            "textQuery": place.name, "maxResultCount": 3, "languageCode": "ko",
            "locationBias": {"circle": {"center": {"latitude": place.lat, "longitude": place.lng}, "radius": 300.0}},
        }, mask)
        for d in body.get("places", []):
            cand = _parse(d)
            if cand and is_same_place(place.name, place.lat, place.lng, cand):
                return {"phone": d.get("nationalPhoneNumber"), "rating": d.get("rating"),
                        "rating_count": d.get("userRatingCount"),
                        "price_level": _price_level(d.get("priceLevel")),
                        "opening_hours": _hours(d.get("regularOpeningHours"))}
        return {}


def _price_level(raw: str | None) -> str | None:
    if not raw or raw == "PRICE_LEVEL_UNSPECIFIED":
        return None
    return raw.removeprefix("PRICE_LEVEL_")


def _hours(raw: dict[str, Any] | None) -> tuple[str, ...] | None:
    days = (raw or {}).get("weekdayDescriptions")
    return tuple(days) if days else None


def _parse(d: dict[str, Any]) -> RawPlace | None:
    try:
        loc = d["location"]
        types = d.get("types", [])
        category = next((c for t, c in _CATEGORY_OF_TYPE if t in types), "기타")
        return RawPlace(
            source="google",
            source_id=d["id"],
            name=d["displayName"]["text"],
            lat=float(loc["latitude"]),
            lng=float(loc["longitude"]),
            category=category,
            address=d.get("formattedAddress") or None,
            place_url=d.get("googleMapsUri") or None,
            contributed_by=("google",),
        )
    except (KeyError, ValueError, TypeError):
        return None
