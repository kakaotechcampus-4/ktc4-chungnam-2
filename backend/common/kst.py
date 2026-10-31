"""KST 날짜 경계 한 곳(#766). 하루 상한(agent, agent/course)과 광고 집계 날짜(ads)가 이것으로 하루를 자른다.

Asia/Seoul은 서머타임이 없어(1988년 이후) +9시간 고정 오프셋과 같다. zoneinfo는 Windows에서 tzdata 패키지가
있어야 해서 쓰지 않는다.
"""

from datetime import date, datetime, timedelta, timezone

KST = timezone(timedelta(hours=9), "KST")


def kst_date(now: datetime) -> date:
    """now가 속한 KST 날짜. now는 timezone-aware여야 한다."""
    if now.tzinfo is None:
        raise ValueError("now는 timezone-aware여야 합니다 — naive datetime은 KST/UTC 혼동을 부른다")
    return now.astimezone(KST).date()


def kst_day_start(now: datetime) -> datetime:
    """now가 속한 KST 하루의 시작(자정, KST aware). 같은 순간을 UTC로 쓰려면 `.astimezone(timezone.utc)`를 붙인다."""
    d = kst_date(now)
    return datetime(d.year, d.month, d.day, tzinfo=KST)
