"""힌트 → 자체 DB 장소 한 건 매칭의 판단(순수 함수). DB를 모른다 — 후보 목록을 받아 고른다.

원칙: 엉뚱한 곳에 핀이 꽂히는 것보다 거절(None)이 낫다. 확신이 낮으면 None.
실제 DB 구현(api.match_place)과 메모리 대역(testing.FakePlaces)이 같은 규칙을 쓰도록 여기 한 곳에 둔다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from places.schemas import PlaceHint, PlaceMatch
from places.sources.base import distance_m

OWN_CATEGORIES = ("음식점", "카페", "관광지")   # 자체 DB가 담는 분류 — 숙소·기타는 v1에서 없다(#191)
MAX_RADIUS_M = 300.0     # 힌트 좌표에서 이 거리 안의 후보만 본다
MAX_CANDIDATES = 20      # DB에서 가져올 후보 수 상한(가까운 순)
NAME_MIN_SCORE = 0.8     # 이름 유사도가 이보다 낮으면 같은 곳으로 보지 않는다
AMBIGUITY_GAP_M = 30.0   # 이름 점수가 비슷한 2등이 1등보다 이만큼 더 멀어야 1등을 고른다(동명 점포)
_SCORE_TIE = 0.05

_PAREN = re.compile(r"[\(\[（][^\)\]）]*[\)\]）]")
_NON_WORD = re.compile(r"[^0-9a-z가-힣]")


@dataclass(frozen=True)
class Candidate:
    """매칭 후보 — places 한 행에서 매칭에 필요한 값만."""

    place_id: str
    name: str
    lat: float
    lng: float
    category: str
    kakao_place_id: str | None = None


def normalize_name(name: str) -> str:
    """괄호 안(지점 표기 등)·공백·기호를 지우고 소문자로 맞춘다."""
    return _NON_WORD.sub("", _PAREN.sub("", name).lower())


def name_score(a: str, b: str) -> float:
    """0~1. 같으면 1, 한쪽이 다른 쪽을 통째로 포함하면 길이 비율, 아니면 문자열 유사도."""
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    short, long_ = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(short) >= 2 and short in long_:
        ratio = len(short) / len(long_)
        return max(ratio, 0.85) if ratio >= 0.5 else ratio   # "스타벅스 성수점" ⊃ "스타벅스": 절반 이상이면 같은 곳 후보
    return SequenceMatcher(None, na, nb).ratio()


def pick_match(hint: PlaceHint, candidates: Sequence[Candidate]) -> PlaceMatch | None:
    # 1) 이미 이 카카오 장소 ID로 매칭된 적 있는 자체 DB 장소가 있으면 그것(분류가 같을 때만)
    if hint.kakao_place_id:
        for c in candidates:
            if c.kakao_place_id == hint.kakao_place_id and c.category == hint.category:
                return _match(c)

    scored: list[tuple[float, float, Candidate]] = []
    for c in candidates:
        if c.category != hint.category:
            continue
        dist = distance_m(hint.lat, hint.lng, c.lat, c.lng)
        if dist > MAX_RADIUS_M:
            continue
        score = name_score(hint.name, c.name)
        if score >= NAME_MIN_SCORE:
            scored.append((score, dist, c))
    if not scored:
        return None

    scored.sort(key=lambda t: (-t[0], t[1]))
    best_score, best_dist, best = scored[0]
    for score, dist, _ in scored[1:]:
        # 이름이 거의 같은 다른 점포가 비슷한 거리에 있으면 어느 쪽인지 알 수 없다 → 거절
        if best_score - score <= _SCORE_TIE and dist - best_dist < AMBIGUITY_GAP_M:
            return None
    return _match(best)


def _match(c: Candidate) -> PlaceMatch:
    return PlaceMatch(place_id=c.place_id, name=c.name, lat=c.lat, lng=c.lng, category=c.category)
