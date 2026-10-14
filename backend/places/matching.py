"""힌트 → 자체 DB 장소 한 건 매칭의 판단(순수 함수). DB를 모른다 — 후보 목록을 받아 고른다.

원칙: 엉뚱한 곳에 핀이 꽂히는 것보다 거절(None)이 낫다. 확신이 낮으면 None.
반경은 여기서 다시 재지 않는다 — 후보를 건네는 쪽(repository의 ST_DWithin)이 한 번만 판정한다(#316).
실제 DB 구현(api.match_place)과 메모리 대역(testing.FakePlaces)이 같은 규칙을 쓰도록 여기 한 곳에 둔다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Sequence

from common import categories
from places.schemas import PlaceHint, PlaceMatch

OWN_CATEGORIES = categories.pinnable()   # 자체 DB가 담는 분류(common/categories.py, #191·#280)
MAX_RADIUS_M = 300.0     # 힌트 좌표에서 이 거리 안의 후보만 본다 — 판정은 후보를 주는 쪽(DB의 ST_DWithin)이 한다
MAX_CANDIDATES = 20      # DB에서 가져올 후보 수 상한(가까운 순)
NAME_MIN_SCORE = 0.8     # 이름 유사도가 이보다 낮으면 같은 곳으로 보지 않는다
ADDRESS_NAME_MIN_SCORE = 0.5   # 주소가 일치할 때만 이 점수까지 내려 같은 곳으로 본다(#500) — 이름이 전혀 다르면 같은 건물의 다른 가게다
AMBIGUITY_GAP_M = 30.0   # 이름 점수가 비슷한 2등이 1등보다 이만큼 더 멀어야 1등을 고른다(동명 점포)
_SCORE_TIE = 0.05

_PAREN = re.compile(r"[\(\[（][^\)\]）]*[\)\]）]")
_NON_WORD = re.compile(r"[^0-9a-z가-힣]")
_ROAD_SPACE = re.compile(r"(로)\s+(\d+(?:번)?길)")                       # "논현로 12길" → "논현로12길"
_ROAD_ADDR = re.compile(r"([가-힣]+\d*(?:로|길))\s*(\d+)(?:-(\d+))?")   # 도로명 + 건물번호
_LOT_ADDR = re.compile(r"([가-힣]+(?:\d가|동|리))\s*(\d+)(?:-(\d+))?")  # 법정동·리 + 지번


@dataclass(frozen=True)
class Candidate:
    """매칭 후보 — places 한 행에서 매칭에 필요한 값만."""

    place_id: str
    name: str
    lat: float
    lng: float
    category: str
    kakao_place_id: str | None = None
    distance_m: float | None = None   # 힌트 좌표까지 DB가 잰 ST_Distance. 카카오 ID로만 붙은 후보는 None(반경 밖일 수 있다)
    address: str | None = None        # 자체 DB의 주소. 힌트 주소와의 비교(#500)에만 쓴다


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


def normalize_address(address: str) -> tuple[str, str] | None:
    """주소를 비교 키 (종류, 값)으로 줄인다. 도로명(`성수이로 100`)이 있으면 그것, 없으면 지번(`성수동2가 300-1`).
    시·구 이름·층·호·괄호 표기는 버린다. 읽어 낼 수 없으면 None."""
    text = _ROAD_SPACE.sub(r"\1\2", _PAREN.sub(" ", address))
    for kind, pattern in (("road", _ROAD_ADDR), ("lot", _LOT_ADDR)):
        m = pattern.search(text)
        if m:
            main, sub = m.group(2).lstrip("0") or "0", m.group(3)
            return kind, f"{m.group(1)}|{main}" + (f"-{sub.lstrip('0') or '0'}" if sub else "")
    return None


def address_agreement(a: str | None, b: str | None) -> bool | None:
    """True 같은 번지 · False 같은 종류의 주소인데 다르다 · None 비교할 수 없다(한쪽이 없거나 종류가 다르다).
    번지의 본번만 같고 한쪽에 부번이 없으면 같은 건물일 수 있어 판단을 미룬다(None)."""
    if not a or not b:
        return None
    ka, kb = normalize_address(a), normalize_address(b)
    if ka is None or kb is None or ka[0] != kb[0]:
        return None
    if ka[1] == kb[1]:
        return True
    (street_a, _, num_a), (street_b, _, num_b) = (k[1].partition("|") for k in (ka, kb))
    if street_a == street_b and num_a.split("-")[0] == num_b.split("-")[0] and ("-" in num_a) != ("-" in num_b):
        return None
    return False


def pick_match(hint: PlaceHint, candidates: Sequence[Candidate]) -> PlaceMatch | None:
    # 1) 이미 이 카카오 장소 ID로 매칭된 적 있는 자체 DB 장소가 있으면 그것(분류가 같을 때만)
    if hint.kakao_place_id:
        for c in candidates:
            if c.kakao_place_id == hint.kakao_place_id and c.category == hint.category:
                return _match(c)

    # (이름 점수, 거리, 주소 일치 여부, 후보) — 주소가 다른 후보(False)는 다른 점포라 처음부터 뺀다(#500)
    strong: list[tuple[float, float, bool, Candidate]] = []    # 이름만으로 충분한 후보
    rescued: list[tuple[float, float, bool, Candidate]] = []   # 이름은 모자라지만 주소가 같은 후보
    for c in candidates:
        if c.category != hint.category:
            continue
        agree = address_agreement(hint.address, c.address)
        if agree is False:
            continue
        # 동명 점포 구분용 상대 거리 — DB 값을 그대로 쓴다. None(카카오 ID로만 붙은 후보)은 가장 먼 것으로 본다
        dist = c.distance_m if c.distance_m is not None else math.inf
        score = name_score(hint.name, c.name)
        if score >= NAME_MIN_SCORE:
            strong.append((score, dist, agree is True, c))
        elif agree is True and score >= ADDRESS_NAME_MIN_SCORE:
            rescued.append((score, dist, True, c))
    scored = strong or rescued   # 이름만으로 충분한 후보가 있으면 이름이 모자란 후보는 보지 않는다
    if not scored:
        return None

    scored.sort(key=lambda t: (not t[2], -t[0], t[1]))   # 주소가 같은 후보 → 이름 점수 → 가까운 순
    best_score, best_dist, best_addr, best = scored[0]
    for score, dist, addr, _ in scored[1:]:
        # 이름이 거의 같은 다른 점포가 비슷한 거리에 있으면 어느 쪽인지 알 수 없다 → 거절. 주소가 같다고 확인된 쪽이 이기면 모호하지 않다
        if addr != best_addr:
            continue
        if best_score - score <= _SCORE_TIE and dist - best_dist < AMBIGUITY_GAP_M:
            return None
    return _match(best)


def _match(c: Candidate) -> PlaceMatch:
    return PlaceMatch(place_id=c.place_id, name=c.name, lat=c.lat, lng=c.lng, category=c.category)
