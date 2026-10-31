"""크레딧 순수 규칙 — 원장 ref_id 모양과 가격 찾기(docs/credits-reviews.md 3.3절). DB를 모른다."""

from credits.constants import PRICES


def price_of(feature: str) -> int:
    """가격표에 있는 feature의 가격. 표에 없으면 ValueError — 크레딧을 쓰지 않는 기능은 charge를 부르지 않는다."""
    try:
        return PRICES[feature]
    except KeyError:
        raise ValueError(f"가격표(credits/constants.py PRICES)에 없는 feature: {feature}") from None


def initial_ref(user_id: str) -> str:
    return f"initial:{user_id}"


def spend_ref(feature: str, run_id: str) -> str:
    return f"{feature}:{run_id}"


def refund_ref(spend: str) -> str:
    return f"refund:{spend}"


def review_ref(user_id: str, place_id: str) -> str:
    return f"review:{user_id}:{place_id}"
