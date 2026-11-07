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
# 도로명 주소는 한 정규식의 백트래킹에 맡기지 않고 단계로 읽는다(#1019): ① 도로명 토큰 → ② 분기 도로(번길·안길·N길·N가길) 최대 한 번 →
# ③ 건물번호가 반드시 와야 한다. ③이 없으면 분기 번호를 건물번호로 되돌려 읽지 않고 도로명 주소가 아니라고 본다(모름).
# 범위를 일부러 좁혔다 — 미탐(None)은 「하나씩 찍기」로 가는 안전한 쪽이고 오탐은 엉뚱한 핀이다. 실제 적재 주소는 `아차산로17번길 4`처럼 붙여 쓴다.
#  - 분기 접미사 앞에 공백이 낀 표기(`14 길`, `17 번길`, `5 가길`)는 읽지 않는다: 도로명 주소도 지번도 아니다(None).
#  - 분기 접미사의 한글은 도로명주소법의 가지번호(가나다라마바사아자차카타파하)뿐이다. `꽃길`·`한길`은 분기가 아니라 건물·지명이다.
_BRANCH_CHAR = "가나다라마바사아자차카타파하"
_BRANCH_SUFFIX = rf"(?:번길|안길|[{_BRANCH_CHAR}]?길)"
_BRANCH_BARE = rf"{_BRANCH_SUFFIX}(?![가-힣])"             # 번길·안길·가길·길 — 단독으로는 도로명이 아니다
_BRANCH_TOKEN = rf"\d+{_BRANCH_SUFFIX}(?![가-힣])"         # 17번길·14길·5가길(붙여 쓴 것만)
_NOT_ADMIN = "".join(f"(?<!{x})" for x in ("특별시", "광역시", "특별자치시", "특별자치도")) + "(?<![도시군구읍면])"   # 행정구역 이름(성동구)을 도로명으로 삼키지 않는다
_ROAD_HEAD = re.compile(   # 공백을 가로지르지 않는다. 뒤에 한글이 이어지면(한길빌딩) 도로명이 아니다
    rf"(?<![가-힣\d])(?!{_BRANCH_TOKEN})(?!{_BRANCH_BARE})"   # 분기 토큰·접미사 단독은 head가 될 수 없다
    r"(?:\d*[가-힣]+\d*(?:로|길)(?![가-힣])"                      # 성수이로·중앙1로·1공단로·테헤란로14길
    rf"|[가-힣]+\d+{_BRANCH_SUFFIX}(?![가-힣])"                    # 상도13가길·연무장5가길(이름에 붙은 분기)
    rf"|[가-힣]+{_NOT_ADMIN}(?=\s+{_BRANCH_TOKEN}))")             # 연무장 5가길(이름 뒤 공백 분기, 행정구역 이름은 제외)
_ROAD_BRANCH = re.compile(rf"\s*{_BRANCH_TOKEN}")
_HEAD_HAS_BRANCH = re.compile(rf"\d+{_BRANCH_SUFFIX}$")
_NUMBER_TAIL = rf"(?:번지)?(?![가-힣a-zA-Z\d]|-\d|\s*{_BRANCH_BARE})"   # 101호·1F처럼 한글·영문·숫자가 이어지거나 공백 뒤 분기 접미사가 오면 건물번호·지번이 아니다
_ROAD_NUMBER = re.compile(r"\s*(?:지하\s*)?(\d+)(?:-(\d+))?" + _NUMBER_TAIL)
_WS = re.compile(r"\s+")
_LOT_ADDR = re.compile(r"(?<![가-힣\d])([가-힣]+(?:\d가|동|리))\s*(\d+)(?:-(\d+))?" + _NUMBER_TAIL)   # 법정동·리 + 지번(`산` 번지는 읽지 않는다 — 일반 번지와 다른 필지)


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
    kakao_place_url: str | None = None   # 이미 기록된 카카오 장소 URL. 링크 해석 결과의 place_source.url(#1486)에만 쓴다
    source: str | None = None             # places.source(permit | tourapi). 링크 해석 결과의 place_source.provider(#1486)에만 쓴다


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


def _road_address(text: str) -> tuple[str, int] | None:
    """(도로명주소 키, 건물번호가 끝나는 위치). 못 읽으면 None."""
    for head in _ROAD_HEAD.finditer(text):
        if re.search(r"\d\s*$", text[: head.start()]):
            continue   # 번지 숫자 바로 뒤의 말(100 꽃길)은 도로명이 아니다
        pos, parts = head.end(), [head.group(0)]
        if not _HEAD_HAS_BRANCH.search(head.group(0)):
            branch = _ROAD_BRANCH.match(text, pos)   # 분기 도로는 최대 한 번 — 되돌아가 건물번호로 읽지 않는다
            if branch:
                parts.append(branch.group(0))
                pos = branch.end()
        number = _ROAD_NUMBER.match(text, pos)
        if number:
            main, sub = number.group(1).lstrip("0") or "0", number.group(2)
            return f"{_WS.sub('', ''.join(parts))}|{main}" + (f"-{sub.lstrip('0') or '0'}" if sub else ""), number.end()
    return None


def _parse_road(text: str) -> str | None:
    found = _road_address(text)
    return found[0] if found else None


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


_BRANCH_NAME_SUFFIX = re.compile(r"(?:본점|분점)$")
_PROVINCE = re.compile(
    r"^(?:대한민국\s+)?(?:서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)"
    r"(?:특별시|광역시|특별자치시|특별자치도|도)?\s+\S+")
_FLOOR_TAIL = re.compile(r"^(?:[\s,]*(?:지하|B)?\s*\d+\s*(?:층|호))+")   # 주소 뒤의 층·호 꼬리


def branch_suffix(name: str) -> str | None:
    """이름의 지점 접미사 낱말(정규형): 마지막 낱말이 「점」으로 끝나면 그 낱말(명동본점), 낱말이 하나뿐이면 끝의 본점·분점. 없으면 None."""
    words = _PAREN.sub(" ", name).split()
    if len(words) >= 2 and words[-1].endswith("점"):
        return normalize_name(words[-1])
    m = _BRANCH_NAME_SUFFIX.search(" ".join(words))
    return m.group(0) if m and len(words) == 1 and len(words[0]) > len(m.group(0)) else None


def strip_branch_suffix(name: str) -> str:
    """지점 접미사를 뗀 이름(비교 전용): 마지막 낱말이 「점」으로 끝나면(명동본점·성수점·안국역점) 그 낱말을 떼고, 낱말이 하나뿐이면
    끝의 본점·분점만 뗀다. 점이 아닌 이름은 그대로. 주소가 같다고 확인된 경우에만 쓴다 — 이름만으로는 다른 지점을 가르지 못한다."""
    words = _PAREN.sub(" ", name).split()
    if len(words) >= 2 and words[-1].endswith("점"):
        return " ".join(words[:-1])
    return _BRANCH_NAME_SUFFIX.sub("", " ".join(words)).strip() or name


def split_address_and_name(text: str) -> tuple[str, str] | None:
    """「시·도로 시작하는 도로명주소 + 상호」(구글 링크 이름이 이렇게 온다, #1047)를 (주소, 상호)로 나눈다.
    주소는 건물번호까지고 그 뒤 층·호(`1층`, `지하1층`)는 버린다. 시·도로 시작하지 않거나 도로명주소를 못 읽거나 상호가 비면 None."""
    text = text.strip()
    if not _PROVINCE.match(text):
        return None
    found = _road_address(_PAREN.sub(lambda m: " " * len(m.group(0)), text))   # 괄호를 같은 길이 공백으로 바꿔 위치를 보존한다
    if found is None:
        return None
    end = found[1]
    rest = _FLOOR_TAIL.sub("", text[end:].lstrip(" ,"))
    name = rest.strip(" ,")
    return (text[:end].strip(), name) if name else None


def address_search_term(address: str) -> str | None:
    """주소 후보 조회가 DB를 좁히는 검색어: 도로명 앞부분(아차산로·창덕궁). 두 글자면 trigram 인덱스를 못 타니 붙여 쓴 도로명 전체.
    도로명주소가 아니면 None(지번은 이 조회를 하지 않는다)."""
    key = normalize_address(address)
    if key is None or key[0] != "road":
        return None
    street = key[1].partition("|")[0]
    head = re.match(r"[가-힣]+", street)
    if head is None:
        return None
    return head.group(0) if len(head.group(0)) >= 3 else street


ADDRESS_CANDIDATE_MAX_ROWS = 2000   # 같은 도로명이 이만큼 넘으면 유일성을 말할 수 없어 빈 목록


_SIDO = {
    "서울": "서울", "서울특별시": "서울", "부산": "부산", "부산광역시": "부산", "대구": "대구", "대구광역시": "대구", "인천": "인천", "인천광역시": "인천",
    "광주": "광주", "광주광역시": "광주", "대전": "대전", "대전광역시": "대전", "울산": "울산", "울산광역시": "울산", "세종": "세종",
    "세종특별자치시": "세종", "경기": "경기", "경기도": "경기", "강원": "강원", "강원도": "강원", "강원특별자치도": "강원",
    "충북": "충북", "충청북도": "충북", "충남": "충남", "충청남도": "충남", "전북": "전북", "전라북도": "전북", "전북특별자치도": "전북",
    "전남": "전남", "전라남도": "전남", "경북": "경북", "경상북도": "경북", "경남": "경남", "경상남도": "경남",
    "제주": "제주", "제주도": "제주", "제주특별자치도": "제주",
}


def address_region(address: str | None) -> tuple[str | None, str | None]:
    """주소 앞머리의 (시·도, 시·군·구). 시·도는 줄임말(서울/서울특별시, 충남/충청남도)을 같은 값으로 본다. 읽지 못하면 None."""
    tokens = [t for t in _PAREN.sub(" ", address or "").split() if t != "대한민국"]
    sido = _SIDO.get(tokens[0]) if tokens else None
    if sido is None:
        return None, None
    gu = tokens[1] if len(tokens) > 1 and tokens[1][-1:] in ("시", "군", "구") else None
    return sido, gu


def same_region(a: str | None, b: str | None) -> bool:
    """이름 근거가 없는 경로용: 시·도가 둘 다 읽히고 같아야 하고, 시·군·구가 둘 다 있으면 같아야 한다. 하나라도 읽을 수 없으면 False."""
    (sido_a, gu_a), (sido_b, gu_b) = address_region(a), address_region(b)
    if sido_a is None or sido_a != sido_b:
        return False
    return gu_a is None or gu_b is None or gu_a == gu_b


def pick_address_candidate(address: str, candidates: Sequence[Candidate]) -> list[Candidate]:
    """같은 도로명주소(건물번호까지)에 영업 중인 후보가 정확히 한 곳일 때만 [그 곳](이름은 보지 않는다). 둘 이상(다중 입점)이거나
    주소를 비교할 수 없으면 []. 자동 확정이 아니라 사람이 확인할 후보다.
    도로명 키는 시·구 이름을 버리므로 이름 근거가 없는 이 경로에서는 시·도(와 시·군·구)가 어긋나거나 입력의 시·도를 후보에서 확인할 수 없는
    후보를 뺀다 — 서로 다른 지역의 같은 도로명·번호(대전 중앙로 48 ↔ 제주 중앙로 48)를 같은 곳으로 보지 않는다."""
    same = [c for c in candidates if c.category in OWN_CATEGORIES and address_agreement(address, c.address) is True and same_region(address, c.address)]
    return same if len(same) == 1 else []


def hint_like_prefixes(name: str) -> list[str]:
    """상호명 힌트로 후보를 좁힐 name_norm 접두 검색어: 이름의 정규형과, 지점 접미사를 뗀 정규형(스타벅스 광화문점 → 스타벅스).
    뗀 이름은 주소가 같다고 확인될 때만 쓰이지만 후보는 먼저 모아야 하므로 같이 조회한다. 정규형이 비면 []."""
    nq = normalize_name(name)
    if not nq:
        return []
    stripped = normalize_name(strip_branch_suffix(name))
    return [nq] if len(stripped) < _HINT_MIN_PREFIX or stripped == nq else [nq, stripped]


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
        mine, theirs = branch_suffix(name), branch_suffix(c.name)
        if agree is True and mine and theirs and mine != theirs:
            continue   # 둘 다 지점명이 있고 다르다(왕비집 명동본점 ↔ 왕비집 신세계점) — 같은 건물의 다른 지점이라 이름이 비슷해도 확정하지 않는다
        score = name_score(name, c.name)
        if agree is True and score < NAME_MIN_SCORE and (mine or theirs) and not (mine and theirs):
            # 주소가 같다고 확인된 때만, 한쪽에만 지점 접미사가 있으면 그것을 뗀 이름이 다른 쪽과 같을 때 이름 일치로 본다(왕비집 명동본점 ↔ 왕비집)
            base_in, base_db = normalize_name(strip_branch_suffix(name)), normalize_name(strip_branch_suffix(c.name))
            if len(base_in) >= 2 and base_in == base_db:
                score = 1.0
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
