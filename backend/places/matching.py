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
# 도로명 주소는 한 정규식의 백트래킹에 맡기지 않고 단계로 읽는다(#1019): ① 도로명 토큰 → ② 분기 도로(번길·안길·N길·N가길)를 끝까지 →
# ③ 건물번호가 반드시 와야 한다. ③이 없으면 분기 번호를 건물번호로 되돌려 읽지 않고 도로명 주소가 아니라고 본다(모름).
_BRANCH_END = r"\d+(?:\s*(?:번길|안길)|[가-힣]?길)(?![가-힣])"   # 17번길·17 번길·17안길·14길·5가길·12나길. 건물명의 「길」(100 한길빌딩)은 잇지 않는다
_ROAD_HEAD = re.compile(   # 공백을 가로지르지 않는다. 뒤에 한글이 이어지면(한길빌딩) 도로명이 아니다
    r"(?<![가-힣\d])(?:\d*[가-힣]+(?:로|길)(?![가-힣])|[가-힣]+(?=\s*" + _BRANCH_END + "))")   # 성수이로·1공단로·연무장(5가길 앞)
_ROAD_BRANCH = re.compile(r"\s*" + _BRANCH_END)
_ROAD_NUMBER = re.compile(r"\s*(?:지하\s*)?(\d+)(?:-(\d+))?(?:번지)?(?![가-힣\d]|-\d)")   # 101호처럼 한글·숫자가 이어지면 건물번호가 아니다
_WS = re.compile(r"\s+")
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


def _parse_road(text: str) -> str | None:
    for head in _ROAD_HEAD.finditer(text):
        pos, parts = head.end(), [head.group(0)]
        while branch := _ROAD_BRANCH.match(text, pos):   # 분기 도로를 끝까지 — 되돌아가 건물번호로 읽지 않는다
            parts.append(branch.group(0))
            pos = branch.end()
        number = _ROAD_NUMBER.match(text, pos)
        if number:
            main, sub = number.group(1).lstrip("0") or "0", number.group(2)
            return f"{_WS.sub('', ''.join(parts))}|{main}" + (f"-{sub.lstrip('0') or '0'}" if sub else "")
    return None


def normalize_address(address: str) -> tuple[str, str] | None:
    """주소를 비교 키 (종류, 값)으로 줄인다. 도로명(`성수이로 100`, `아차산로17번길 4`)이 있으면 그것, 없으면 지번(`성수동2가 300-1`).
    시·구 이름·층·호·괄호 표기는 버린다. 읽어 낼 수 없으면 None. `을지로3가 100`의 3가는 도로명이 아니라 법정동이다."""
    text = _PAREN.sub(" ", address)
    road = _parse_road(text)
    if road is not None:
        return "road", road
    m = _LOT_ADDR.search(text)
    if m:
        main, sub = m.group(2).lstrip("0") or "0", m.group(3)
        return "lot", f"{m.group(1)}|{main}" + (f"-{sub.lstrip('0') or '0'}" if sub else "")
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


LINK_MATCH_RADIUS_M = 100.0   # 구글 링크 좌표에서 이 거리 안의 자체 DB 장소만 본다(#474)
LINK_MAX_MATCHES = 5


def pick_link_matches(name_hint: str, candidates: Sequence[Candidate]) -> list[Candidate]:
    """구글 링크의 이름과 같은 곳으로 볼 만한 후보만, 가까운 순 최대 LINK_MAX_MATCHES. 이름이 안 맞으면 버린다 —
    같은 건물의 다른 가게를 내밀지 않는다. 반경은 후보를 주는 쪽(DB)이 판정했다."""
    kept = [c for c in candidates if c.category in OWN_CATEGORIES and name_score(name_hint, c.name) >= NAME_MIN_SCORE]
    kept.sort(key=lambda c: (c.distance_m if c.distance_m is not None else math.inf, c.place_id))
    return kept[:LINK_MAX_MATCHES]


HINT_MAX_CANDIDATES = 50   # 이름 일치 후보가 이만큼 넘으면 체인점 수준으로 흔한 이름이라 고르지 않는다(좌표가 없어 거리로 못 가린다)
_HINT_MIN_PREFIX = 2


def hint_name_keys(name: str) -> tuple[str, list[str]]:
    """상호명 힌트로 자체 DB 후보를 좁히는 키(name_norm 기준). (정규형, 정규형의 2자 이상 앞부분들).
    DB 이름이 힌트로 시작하거나(접두 검색) 힌트가 DB 이름으로 시작할 때(앞부분 정확 일치)만 후보다 — 둘 다 name_norm 인덱스를 탄다.
    정규형이 비면 ("", [])."""
    nq = normalize_name(name)
    if not nq:
        return "", []
    return nq, [nq[:i] for i in range(_HINT_MIN_PREFIX, len(nq) + 1)]


def pick_hint_match(name: str, address: str | None, candidates: Sequence[Candidate]) -> list[Candidate]:
    """상호명·주소만 아는 힌트(좌표 없음, #946)의 짝. 짝이 하나로 확실할 때만 [그 하나], 아니면 [](가드레일 2).
    pick_match는 좌표(거리)나 주소로 확정 근거를 얻는다. 여기는 좌표가 없으니 **주소가 같다고 확인된 후보만** 확정한다 —
    입력 주소가 없거나 후보 주소를 비교할 수 없으면(모름) 이름만으로 확정하지 않는다. DB에 일부 지점만 있어 후보가 하나뿐이어도
    그것이 같은 점포라는 근거가 못 된다(체인·흔한 이름).
    유일성은 주소가 다르다(False)고 판명된 후보만 뺀 전부로 본다 — 주소가 같은 후보와 주소를 모르는 후보를 함께 겨룬다.
    같은 이름 기준(strong ≥ NAME_MIN_SCORE, 주소가 같을 때만 ADDRESS_NAME_MIN_SCORE까지 구제)을 통과한 다른 후보의 점수가
    1등과 _SCORE_TIE 이내(1등보다 높은 경우 포함)면 어느 쪽인지 알 수 없어 거절한다."""
    if not address or not address.strip():
        return []
    rivals: list[tuple[float, bool, Candidate]] = []
    for c in candidates:
        if c.category not in OWN_CATEGORIES:
            continue
        agree = address_agreement(address, c.address)
        if agree is False:
            continue
        score = name_score(name, c.name)
        if score >= NAME_MIN_SCORE or (agree is True and score >= ADDRESS_NAME_MIN_SCORE):
            rivals.append((score, agree is True, c))
    confirmed = [r for r in rivals if r[1]]
    if not confirmed:
        return []
    best_score, _, best = max(confirmed, key=lambda t: (t[0], t[2].place_id))
    for score, _, other in rivals:
        if other is not best and score >= best_score - _SCORE_TIE:
            return []
    return [best]


def _match(c: Candidate) -> PlaceMatch:
    return PlaceMatch(place_id=c.place_id, name=c.name, lat=c.lat, lng=c.lng, category=c.category)
