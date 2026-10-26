"""휴무 글 읽기(인수인계 4절) — TourAPI 등 공공데이터의 `rest_days` 글을 요일별 영업 상태로 바꾼다. 순수 함수.

원칙: 모르면 모른다. 글에서 확실히 읽힌 것만 `closed`/`open`으로 두고, 나머지는 `unknown`이다.
- 읽히는 것: 연중무휴·무휴·휴무 없음, "매주 X요일", "X요일~Y요일", "X요일, Y요일", "주말", 요일 없는 공휴일·명절 휴무.
- 공휴일·명절 휴무는 요일 판정에서 뺀다(날짜가 공휴일인지는 이 함수의 몫이 아니다).
- 모르는 것: 격주·첫째·마지막·매월·매년, "공연별로 상이", 빈 글, 대괄호로 나뉜 글, 이해하지 못한 조각.
  이해하지 못한 조각이 있으면 이미 closed로 읽힌 요일만 남기고 나머지는 unknown으로 낮춘다.
"""

from __future__ import annotations

import re
from typing import Mapping, Optional, cast

from agent.course.core import DayStatus
from places import api as places_api

_DAYS = "월화수목금토일"
_ALL_UNKNOWN: dict[int, DayStatus] = {wd: "unknown" for wd in range(7)}

_NOTE = re.compile(r"※.*", re.S)
_BR = re.compile(r"<br\s*/?>", re.I)
_PAREN = re.compile(r"[(（][^)）]*[)）]")
_BRACKET = re.compile(r"\[[^\]]*\]")
_SEGMENT_SPLIT = re.compile(r"[/／;·]|\+(?=\S)")      # "·"는 설·추석을 쪼개지만 두 조각 모두 공휴일 어휘라 무방하다
_IRREGULAR = re.compile(r"격주|첫째|둘째|셋째|넷째|첫번째|두번째|세번째|네번째|마지막|매월|매년|[0-9]+째|[0-9]+번째|상이|문의|참조|별도|주차|매달|월1회|[0-9]+월(?![0-9]*일)")
_ALWAYS_OPEN = re.compile(r"연중무휴|무휴|휴무없음|휴관없음|휴일없음|쉬는날없음")
_HOLIDAY = re.compile(
    r"공휴일|명절|설날|추석|설$|신정|구정|부처님오신날|크리스마스|성탄절|근로자의날|노동절|선거일|기념일|관장|대체휴일|연휴|당일|전날"
    r"|[0-9]{1,2}월[0-9]{1,2}일"
)
_WEEKEND = re.compile(r"주말")
_DAY_RANGE = re.compile(rf"([{_DAYS}])요일?\s*[~\-～]\s*([{_DAYS}])요일?")
_DAY = re.compile(rf"([{_DAYS}])요일")


def _weekdays_in(text: str) -> set[int]:
    """글 속 요일들(범위는 시작에서 끝까지 한 방향으로 돈다: 일요일~월요일 = 일·월)."""
    found: set[int] = set()
    for a, b in _DAY_RANGE.findall(text):
        i, j = _DAYS.index(a), _DAYS.index(b)
        found.update((i + k) % 7 for k in range((j - i) % 7 + 1))
    stripped = _DAY_RANGE.sub("", text)
    found.update(_DAYS.index(d) for d in _DAY.findall(stripped))
    if _WEEKEND.search(text):
        found.update({5, 6})
    return found


def parse_rest_days(text: Optional[str]) -> dict[int, DayStatus]:
    """휴무 글 → {요일(월=0): open|closed|unknown}. 항상 7요일을 모두 채운다."""
    if text is None or not text.strip():
        return dict(_ALL_UNKNOWN)
    s = _NOTE.sub("", _BR.sub(" ", text)).strip()      # ※ 뒤는 단서다
    if not s or _BRACKET.search(s):
        return dict(_ALL_UNKNOWN)

    parens = _PAREN.findall(s)
    main = _PAREN.sub(" ", s)

    closed: set[int] = set()
    unknown: set[int] = set()
    confusing = False        # 이해하지 못한 조각이 있다 → 안 닫힌 요일은 모름
    open_claim = False       # 연중무휴·휴일 없음을 확인했다

    for raw in _SEGMENT_SPLIT.split(main):
        seg = re.sub(r"\s+", "", raw)
        if not seg:
            continue
        days = _weekdays_in(seg.split("제외")[-1] if "제외" in seg else seg)   # "공휴일을 제외한 월요일"만 요일이 남는다
        if _IRREGULAR.search(seg):
            unknown |= days
            confusing = confusing or not days
        elif _ALWAYS_OPEN.search(seg):
            open_claim = True
            unknown |= days                             # 연중무휴인데 요일도 있다 — 서로 부딪히니 모름
        elif days:
            closed |= days                              # 공휴일 말이 붙어 있어도 요일 휴무는 읽는다
        elif _HOLIDAY.search(seg):
            continue                                    # 공휴일·명절만 — 요일 판정에 안 쓴다
        else:
            confusing = True

    if open_claim:                                       # "연중무휴 (매주 월요일은 포장만)" 같은 괄호 단서는 모름으로 낮춘다
        for p in parens:
            unknown |= _weekdays_in(re.sub(r"\s+", "", p))
        unknown |= closed                                # 연중무휴와 요일 휴무가 한 글에 섞이면(시설별 안내) 어느 쪽인지 모른다
        closed = set()
    elif not closed and not unknown and not confusing and not any(
        _HOLIDAY.search(re.sub(r"\s+", "", r)) for r in _SEGMENT_SPLIT.split(main)
    ):
        return dict(_ALL_UNKNOWN)                        # 읽을 게 하나도 없다

    out: dict[int, DayStatus] = {}
    for wd in range(7):
        if wd in closed:
            out[wd] = "closed"
        elif wd in unknown or confusing:
            out[wd] = "unknown"
        else:
            out[wd] = "open"
    return out


def known_weekdays(hours: Mapping[int, DayStatus]) -> bool:
    """7요일이 모두 open/closed로 판정됐는가."""
    return all(hours.get(wd, "unknown") != "unknown" for wd in range(7))


def merge_sources(*parsed: Mapping[int, DayStatus]) -> dict[int, DayStatus]:
    """여러 칸에서 읽은 결과를 요일별로 합친다. 앞쪽 칸이 우선이고, 모름은 다음 칸이 채운다.
    같은 요일에 open과 closed가 갈리면 보수적으로 unknown이다."""
    out: dict[int, DayStatus] = {}
    for wd in range(7):
        vals = [p.get(wd, "unknown") for p in parsed]
        known = {v for v in vals if v != "unknown"}
        out[wd] = known.pop() if len(known) == 1 else "unknown"
    return out


def read_hours(closed_days: Optional[list[str]], hours: Optional[Mapping[str, list]], fallback_text: Optional[str] = None) -> dict[int, DayStatus]:
    """구조화된 칸(places.api.week_open_status, hours가 closed_days보다 우선)을 먼저 쓰고, `closed_days` 칸 자체가 없을 때만 글 읽기로
    모르는 요일을 채운다(글과 어긋나면 모름)."""
    structured = cast(dict[int, DayStatus], places_api.week_open_status(hours, closed_days))   # 구조화된 칸의 규칙은 places가 한 곳에서 정한다(#747)
    if closed_days is not None:
        return structured
    return merge_sources(structured, parse_rest_days(fallback_text))
