"""크레딧 순수 규칙 — 원장 ref_id 모양, 가격 찾기, 광고 세션 시각(docs/credits-reviews.md 3.3, 3.7절). DB를 모른다."""

import math
from datetime import datetime, timedelta

from credits.constants import AD_MIN_WATCH_S, AD_SESSION_TTL_S, MAX_BALANCE, PRICES


def price_of(feature: str) -> int:
    """가격표에 있는 feature의 가격. 표에 없으면 ValueError — 크레딧을 쓰지 않는 기능은 charge를 부르지 않는다."""
    try:
        return PRICES[feature]
    except KeyError:
        raise ValueError(f"가격표(credits/constants.py PRICES)에 없는 feature: {feature}") from None


def capped_gain(amount: int, balance: int) -> int:
    """잔액 상한(MAX_BALANCE)까지만 채우는 양 — 후기 보상과 환불(명세 3.6절). 이미 상한 이상이면 0(깎지 않는다)."""
    return max(0, min(amount, MAX_BALANCE - balance))


def initial_ref(user_id: str) -> str:
    return f"initial:{user_id}"


def spend_ref(feature: str, run_id: str) -> str:
    return f"{feature}:{run_id}"


def refund_ref(spend: str) -> str:
    return f"refund:{spend}"


def review_ref(user_id: str, place_id: str) -> str:
    return f"review:{user_id}:{place_id}"


def ad_ref(session_id) -> str:
    return f"ad:{session_id}"


def ad_needed(balance: int) -> bool:
    """광고 충전이 필요한 잔액인가 — 가장 싼 가격보다 적다(명세 3.7 「언제 열리나」 3). 가격이 바뀌어도 이 규칙 하나로 따라간다."""
    return balance < min(PRICES.values())


def claim_wait_s(issued_at: datetime, now: datetime) -> int:
    """세션을 연 뒤 받을 수 있을 때까지 남은 초. 0 이상, 올림(1.2초 남았으면 2)."""
    left = (issued_at + timedelta(seconds=AD_MIN_WATCH_S) - now).total_seconds()
    return max(0, math.ceil(left))


def is_expired(issued_at: datetime, now: datetime) -> bool:
    """연 지 AD_SESSION_TTL_S가 지났는가. 받지 않은 세션을 이어 줄지, 받기를 막을지 둘 다 이것으로 본다."""
    return now - issued_at >= timedelta(seconds=AD_SESSION_TTL_S)
