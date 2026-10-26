"""places 순수 규칙 — 영업 중 판정."""

from __future__ import annotations


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
