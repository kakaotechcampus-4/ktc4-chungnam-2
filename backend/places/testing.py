"""places 공개 함수의 메모리 대역 — pins·recommend 세션이 실제 DB·적재 없이 개발·테스트하는 데 쓴다.

실제처럼 동작한다: match_place는 places.matching의 같은 규칙(반경 300m·분류·이름·모호하면 None)을 쓰고,
search_nearby_own은 영업 중인 장소만, get_places는 없는 ID를 키에서 뺀다. 샘플은 서울 가상의 8곳(실제 상호 아님).
카카오 원자료는 어디에도 없다 — kakao_place_id/url만 record_kakao_match로 기록된다.

사용법:
    fake = FakePlaces()
    fake.install(monkeypatch)            # places.api의 6개 함수를 대역으로 바꾼다
    # 또는 pins/recommend에 fake 객체를 직접 주입
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Sequence

from places import matching
from places.matching import OWN_CATEGORIES, Candidate
from places.schemas import Area, FactLabel, PlaceHint, PlaceInfo, PlaceMatch, PlaceRef
from places.sources.base import distance_m

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_NS = uuid.UUID("00000000-0000-0000-0000-00000000f4e5")


def sample_id(key: str) -> str:
    """테스트에서 장소 ID를 예측할 수 있게 키에서 결정적으로 만든다."""
    return str(uuid.uuid5(_NS, key))


@dataclass
class _Row:
    key: str
    name: str
    lat: float
    lng: float
    category: str
    status: str = "open"
    kakao_place_id: str | None = None
    kakao_place_url: str | None = None
    source: str = "permit"

    @property
    def place_id(self) -> str:
        return sample_id(self.key)


def _sample_rows() -> list[_Row]:
    return [
        _Row("seongsu-kalguksu", "성수 칼국수", 37.5445, 127.0561, "음식점"),
        _Row("seongsu-bunsik", "어묵나라 성수점", 37.5446, 127.0562, "음식점"),
        _Row("seongsu-cafe-a", "온도 커피 성수", 37.5439, 127.0556, "카페"),
        _Row("seongsu-cafe-b", "온도 커피 뚝섬", 37.5471, 127.0472, "카페"),
        _Row("seoul-forest", "서울숲", 37.5444, 127.0374, "관광지"),
        _Row("gyeongbok", "경복궁", 37.5796, 126.9770, "관광지"),
        _Row("jongno-closed", "종로 옛날국수", 37.5704, 126.9920, "음식점", status="closed"),
        _Row("hongdae-ramen", "홍대 라멘", 37.5563, 126.9236, "음식점"),
    ]


def _sample_facts() -> dict[str, list[FactLabel]]:
    return {
        sample_id("seongsu-kalguksu"): [
            FactLabel("contains_shellfish", True, "known"),
            FactLabel("spicy_focused", False, "known"),
            FactLabel("price_bucket", "mid", "known"),
            FactLabel("oily_focused", None, "unknown"),
        ],
        sample_id("seongsu-cafe-a"): [
            FactLabel("is_crowded_large", False, "known"),
            FactLabel("quiet", None, "unknown"),
        ],
        sample_id("seoul-forest"): [FactLabel("quiet", True, "known")],
    }


@dataclass
class FakePlaces:
    rows: list[_Row] = field(default_factory=_sample_rows)
    facts: dict[str, list[FactLabel]] = field(default_factory=_sample_facts)

    # ---- 6개 공개 함수 (places.api와 같은 이름·시그니처). db는 메모리 대역이라 받기만 하고 쓰지 않는다 ----

    def match_place(self, hint: PlaceHint, *, db: Session | None = None) -> PlaceMatch | None:
        near = sorted(
            (r for r in self.rows if r.status == "open"
             and distance_m(hint.lat, hint.lng, r.lat, r.lng) <= matching.MAX_RADIUS_M),
            key=lambda r: distance_m(hint.lat, hint.lng, r.lat, r.lng),
        )[: matching.MAX_CANDIDATES]
        # 이미 같은 카카오 ID로 매칭된 장소는 반경 밖이어도 후보에 넣는다(실제 구현의 ID 조회와 같다)
        by_id = [r for r in self.rows if hint.kakao_place_id and r.kakao_place_id == hint.kakao_place_id
                 and r.status == "open" and r not in near]
        return matching.pick_match(hint, [self._candidate(r) for r in near + by_id])

    def record_kakao_match(self, place_id: str, kakao_place_id: str, kakao_place_url: str, *, db: Session | None = None) -> None:
        row = self._row(place_id)
        if row is None:
            raise KeyError(place_id)
        if row.kakao_place_id is None:   # 첫 값 유지 — 실제 구현과 같다(#248)
            row.kakao_place_id, row.kakao_place_url = kakao_place_id, kakao_place_url

    def pinnable_flags(self, hints: Sequence[PlaceHint], *, db: Session | None = None) -> list[bool]:
        return [self.match_place(h) is not None for h in hints]   # 읽기만 한다 — 카카오 ID를 기록하지 않는다

    def get_places(self, place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, PlaceInfo]:
        out: dict[str, PlaceInfo] = {}
        for pid in place_ids:
            row = self._row(pid)
            if row is not None:
                out[pid] = PlaceInfo(pid, row.name, row.lat, row.lng, row.category, row.kakao_place_url, row.source)
        return out

    def search_nearby_own(self, category: str, areas: Sequence[Area], *, db: Session | None = None) -> list[PlaceRef]:
        if category not in OWN_CATEGORIES:
            return []
        return [
            PlaceRef(r.place_id, r.lat, r.lng)
            for r in self.rows
            if r.status == "open" and r.category == category
            and any(distance_m(a.lat, a.lng, r.lat, r.lng) <= a.radius_m for a in areas)
        ]

    def get_facts(self, place_ids: Sequence[str], *, db: Session | None = None) -> dict[str, list[FactLabel]]:
        return {pid: list(self.facts.get(pid, [])) for pid in place_ids}   # 라벨이 없으면 빈 리스트

    # ---- 편의 ----

    def place_id(self, key: str) -> str:
        return sample_id(key)

    def install(self, monkeypatch) -> "FakePlaces":
        """places.api의 6개 공개 함수를 이 대역으로 바꾼다(pytest monkeypatch)."""
        from places import api

        for name in ("match_place", "record_kakao_match", "pinnable_flags", "get_places", "search_nearby_own", "get_facts"):
            monkeypatch.setattr(api, name, getattr(self, name))
        return self

    def _row(self, place_id: str) -> _Row | None:
        return next((r for r in self.rows if r.place_id == place_id), None)

    @staticmethod
    def _candidate(r: _Row) -> Candidate:
        return Candidate(r.place_id, r.name, r.lat, r.lng, r.category, r.kakao_place_id)
