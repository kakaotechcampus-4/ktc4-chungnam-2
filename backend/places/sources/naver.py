"""네이버 지역 검색 API(무료 검색 API) — 2순위. 좌표 검색이 없다: 키워드만 받고 최대 5건을 준다.
그래서 nearby는 "카테고리 키워드로 검색 후 반경으로 거르기"뿐이다(약하다 — for_Root.md 참고)."""

from __future__ import annotations

import re
from typing import Any

from common.geo import haversine_distance_m
from places.http import SourceHttp
from places.sources.base import RawPlace, is_same_place, synthetic_id

URL = "https://openapi.naver.com/v1/search/local.json"
_KEYWORD = {"음식점": "맛집", "카페": "카페", "숙소": "숙소", "관광지": "관광지"}
_TAG = re.compile(r"<[^>]+>")


class NaverPlaceSource:
    name = "naver"
    provides = frozenset({"phone"})

    def __init__(self, http: SourceHttp, client_id: str, client_secret: str) -> None:
        self._http = http
        self._id = client_id
        self._secret = client_secret

    def is_configured(self) -> bool:
        return bool(self._id and self._secret)

    def _search(self, endpoint: str, query: str) -> list[RawPlace]:
        body = self._http.request_json(
            self.name, endpoint, "GET", URL,
            headers={"X-Naver-Client-Id": self._id, "X-Naver-Client-Secret": self._secret},
            params={"query": query, "display": 5, "sort": "random"},
        )
        return [p for p in (_parse(i) for i in body.get("items", [])) if p]

    def search_nearby(self, *, category: str, lat: float, lng: float, radius_m: int) -> list[RawPlace]:
        keyword = _KEYWORD.get(category)
        if keyword is None:
            return []
        return [p for p in self._search("local", keyword) if haversine_distance_m(lat, lng, p.lat, p.lng) <= radius_m]

    def fill(self, place: RawPlace, wanted: frozenset[str]) -> dict[str, Any]:
        if "phone" not in wanted:
            return {}
        for cand in self._search("local", place.name):
            if cand.phone and is_same_place(place.name, place.lat, place.lng, cand):
                return {"phone": cand.phone}
        return {}


def _coord(v: Any) -> float:
    n = float(v)
    return n / 1e7 if abs(n) > 1000 else n   # 현재 응답은 경위도×1e7 정수 문자열이다


def _category(raw: str) -> str:
    head = raw.split(">")[0].strip()
    if head == "음식점":
        return "음식점"
    if "카페" in raw:
        return "카페"
    if head in ("숙박", "숙소") or "호텔" in head:
        return "숙소"
    if "관광" in head or "명소" in head:
        return "관광지"
    return "기타"


def _parse(item: dict[str, Any]) -> RawPlace | None:
    try:
        name = _TAG.sub("", item["title"]).strip()
        lat, lng = _coord(item["mapy"]), _coord(item["mapx"])
        return RawPlace(
            source="naver",
            source_id=synthetic_id(name, lat, lng),
            name=name,
            lat=lat,
            lng=lng,
            category=_category(item.get("category", "")),
            address=item.get("roadAddress") or item.get("address") or None,
            place_url=item.get("link") or None,
            phone=item.get("telephone") or None,
            contributed_by=("naver",),
        )
    except (KeyError, ValueError, TypeError):
        return None
