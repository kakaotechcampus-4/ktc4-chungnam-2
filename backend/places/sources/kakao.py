"""카카오 로컬 API — 1순위. 좌표·카테고리·주소·전화·place_url(층1)을 준다(평점·영업시간은 안 준다)."""

from __future__ import annotations

import logging
from typing import Any

from places.http import SourceError, SourceHttp
from places.sources.base import RawPlace, is_same_place

log = logging.getLogger("pingo.places")

BASE = "https://dapi.kakao.com/v2/local/search"
_GROUP_CODE = {"음식점": "FD6", "카페": "CE7", "숙소": "AD5", "관광지": "AT4"}
_CATEGORY_OF = {v: k for k, v in _GROUP_CODE.items()}
_MAX_RADIUS_M = 20000   # 카카오 로컬 API 반경 상한
_PAGE_SIZE = 15


class KakaoPlaceSource:
    name = "kakao"
    provides = frozenset({"phone"})

    def __init__(self, http: SourceHttp, api_key: str, *, max_pages: int = 2) -> None:
        self._http = http
        self._key = api_key
        self._max_pages = max_pages

    def is_configured(self) -> bool:
        return bool(self._key)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"KakaoAK {self._key}"}

    def search_nearby(self, *, category: str, lat: float, lng: float, radius_m: int) -> list[RawPlace]:
        code = _GROUP_CODE.get(category)
        if code is None:
            return []   # "기타"는 카카오 카테고리 그룹이 없다
        out: list[RawPlace] = []
        for page in range(1, self._max_pages + 1):
            try:
                body = self._http.request_json(
                    self.name, "category", "GET", f"{BASE}/category.json", headers=self._headers(),
                    params={"category_group_code": code, "x": lng, "y": lat, "radius": min(radius_m, _MAX_RADIUS_M),
                            "sort": "distance", "page": page, "size": _PAGE_SIZE},
                )
            except SourceError as exc:
                if page == 1:
                    raise   # 첫 페이지 실패는 소스 실패 — 폴백이 처리한다
                log.warning("places.kakao page=%d 실패, 앞 페이지 결과는 유지: %s", page, exc)
                break
            out.extend(p for p in (_parse(d) for d in body.get("documents", [])) if p)
            if body.get("meta", {}).get("is_end", True):
                break
        return out

    def search_by_name(self, *, query: str, lat: float | None, lng: float | None, limit: int) -> list[RawPlace]:
        """키워드 검색. 좌표가 있으면 가까운 순(반경 제한 없음), 없으면 관련도 순."""
        params: dict[str, Any] = {"query": query, "size": min(limit, _PAGE_SIZE), "page": 1}
        if lat is not None and lng is not None:
            params.update({"x": lng, "y": lat, "sort": "distance"})
        body = self._http.request_json(
            self.name, "keyword", "GET", f"{BASE}/keyword.json", headers=self._headers(), params=params,
        )
        found = (_parse(d) for d in body.get("documents", []))
        return [p for p in found if p][:limit]

    def fill(self, place: RawPlace, wanted: frozenset[str]) -> dict[str, Any]:
        if "phone" not in wanted:
            return {}
        body = self._http.request_json(
            self.name, "keyword", "GET", f"{BASE}/keyword.json", headers=self._headers(),
            params={"query": place.name, "x": place.lng, "y": place.lat, "radius": 300, "size": 5},
        )
        for d in body.get("documents", []):
            cand = _parse(d)
            if cand and cand.phone and is_same_place(place.name, place.lat, place.lng, cand):
                return {"phone": cand.phone}
        return {}


def _parse(d: dict[str, Any]) -> RawPlace | None:
    try:
        return RawPlace(
            source="kakao",
            source_id=str(d["id"]),
            name=d["place_name"],
            lat=float(d["y"]),
            lng=float(d["x"]),
            category=_CATEGORY_OF.get(d.get("category_group_code", ""), "기타"),
            address=d.get("road_address_name") or d.get("address_name") or None,
            place_url=d.get("place_url") or None,
            phone=d.get("phone") or None,
            contributed_by=("kakao",),
        )
    except (KeyError, ValueError, TypeError):
        return None   # 깨진 문서 하나가 검색 전체를 죽이지 않게 건너뛴다
