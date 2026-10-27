"""places 순수 규칙 — 영업 중 판정, 동네와 카카오맵 검색 링크."""

from __future__ import annotations

import re
from urllib.parse import quote


# ---------------------------------------------------------------- 영업 중 판정 (#690)

WEEKDAYS = ("월", "화", "수", "목", "금", "토", "일")   # weekday 0=월 … 6=일 (datetime.date.weekday()와 같다)
_DAY = 24 * 60


def parse_minutes(clock: str) -> int:
    """"HH:MM" → 자정부터의 분. 자정을 넘기면 24를 더한 값("26:00" = 1560)도 읽는다. 형식이 틀리면 ValueError."""
    h, sep, m = clock.partition(":")
    if not sep or not h.isdigit() or not m.isdigit() or len(m) != 2 or int(m) > 59:
        raise ValueError(f"HH:MM 형식이 아니다: {clock!r}")
    return int(h) * 60 + int(m)


def is_open_on(hours: dict | None, closed_days: list[str] | None, weekday: int, minutes: int) -> str:
    """그 요일·시각에 영업 중인가 → "open" | "closed" | "unknown". docs/constraints.md「영업 중 판정」.

    weekday는 0=월 … 6=일, minutes는 자정부터의 분(0~1439). hours는 {"월": [["11:00","21:00"]], …}, 빈 목록 = 휴무.
    - hours가 있으면 오늘 구간 안(시작 <= t < 끝)이거나 어제 구간 중 24:00을 넘는 꼬리 안이면 open, 아니면 closed.
    - hours가 없고(또는 그 요일 키가 없고) closed_days에 오늘 요일이 있으면 closed, 없으면 unknown(영업 중인지는 모른다).
    - 둘 다 없으면 unknown. closed_note·hours_note는 판단에 쓰지 않는다.
    """
    if not 0 <= weekday <= 6 or not 0 <= minutes < _DAY:
        raise ValueError(f"weekday 0~6, minutes 0~1439: {weekday}, {minutes}")
    today = WEEKDAYS[weekday]
    if hours:
        spans = hours.get(today)
        for start, end in spans or ():
            if parse_minutes(start) <= minutes < parse_minutes(end):
                return "open"
        for start, end in hours.get(WEEKDAYS[weekday - 1]) or ():   # weekday - 1 = -1이면 일요일 — 월요일의 어제
            if minutes < parse_minutes(end) - _DAY:
                return "open"
        if spans is not None:
            return "closed"
    if closed_days and today in closed_days:
        return "closed"
    return "unknown"


def day_open_status(hours: dict | None, closed_days: list[str] | None, weekday: int) -> str:
    """요일 하나의 영업 여부 → "open" | "closed" | "unknown" (2026-10-27 결정, #747). 시각은 보지 않는다.

    1. hours에 그 요일 키가 있으면 구간이 있을 때 open, 빈 목록이면 closed. 전날 구간의 자정 넘김 꼬리는 여기서 보지 않는다(is_open_on만 본다).
    2. 아니고 closed_days가 None이 아니면 그 요일이 들어 있을 때 closed, 아니면 open([] = 매일 영업).
    3. 둘 다 없으면 unknown.
    """
    if not 0 <= weekday <= 6:
        raise ValueError(f"weekday 0~6: {weekday}")
    today = WEEKDAYS[weekday]
    if hours and today in hours:
        return "open" if hours[today] else "closed"
    if closed_days is not None:
        return "closed" if today in closed_days else "open"
    return "unknown"


def week_open_status(hours: dict | None, closed_days: list[str] | None) -> dict[int, str]:
    """7요일 전부의 day_open_status → {0..6: 상태}."""
    return {d: day_open_status(hours, closed_days, d) for d in range(7)}


# ---------------------------------------------------------------- 동네와 카카오맵 검색 링크 (#798, #799)
# docs/constraints.md 「카카오맵 검색 링크」. 카카오를 부르지 않고 저장하지 않는다(#53) — 링크 글자만 만든다.

KAKAO_SEARCH_URL = "https://map.kakao.com/link/search/"   # 이 형식은 kakao_search_url 한 곳에서만 쓴다

_SIDO_SUFFIXES = ("특별시", "광역시", "특별자치시", "특별자치도", "도")
_SIDO_SHORT = frozenset({"서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종",
                         "경기", "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"})
_SIGUNGU = re.compile(r"[가-힣]+[시군구]")
_PAREN = re.compile(r"\(([^()]*)\)")
# 괄호 안의 법정동: "우동", "성수동2가", "충무로1가", 읍·면. "1층", "101동", "OO상가" 같은 건물 정보는 거른다
_DONG = re.compile(r"[가-힣][가-힣0-9]*(?:동|[0-9]가|읍|면)")


def _is_sido(token: str) -> bool:
    return token in _SIDO_SHORT or token.endswith(_SIDO_SUFFIXES)


def neighborhood(address: str | None) -> str | None:
    """주소 → 동네 "{시·군·구} {괄호 안 동(읍·면)}". 예 "부산광역시 해운대구 해운대로 1 (우동)" → "해운대구 우동".

    - 시·군·구: 시·도 다음에 이어지는 시·군·구 중 마지막("경기도 수원시 팔달구" → "팔달구"). 세종처럼 없으면 시·도 이름.
    - 동: 괄호 안을 쉼표로 나눈 조각 중 첫 법정동("(1층, 우동)" → "우동"). 괄호가 없으면 시·군·구까지.
    - 주소가 없거나 둘 다 못 찾으면 None.
    """
    if not address or not address.strip():
        return None
    tokens = _PAREN.sub(" ", address).split()
    sido = tokens[0] if tokens and _is_sido(tokens[0]) else None
    sigungu = None
    for token in tokens[1 if sido else 0:]:
        if not _SIGUNGU.fullmatch(token):
            break
        sigungu = token
    dong = next((part for inner in _PAREN.findall(address) for part in (x.strip() for x in inner.split(","))
                 if _DONG.fullmatch(part)), None)
    parts = [p for p in (sigungu or sido, dong) if p]
    return " ".join(parts) or None


def kakao_search_url(query: str) -> str:
    """카카오맵 검색 링크. 검색어는 통째로 URL 인코딩한다(공백 → %20)."""
    return KAKAO_SEARCH_URL + quote(query, safe="")


def place_link(name: str | None, address: str | None, kakao_place_url: str | None) -> str | None:
    """장소 하나의 「카카오맵에서 보기」 링크. 기록된 카카오 장소 URL이 있으면 그것, 없으면 "{이름} {동네}" 검색 링크.
    동네가 없으면 이름만, 이름이 없으면 None."""
    if kakao_place_url:
        return kakao_place_url
    name = (name or "").strip()
    if not name:
        return None
    area = neighborhood(address)
    return kakao_search_url(f"{name} {area}" if area else name)
