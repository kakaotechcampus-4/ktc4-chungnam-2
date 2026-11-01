"""후기 순수 규칙 — 후기를 붙일 장소 찾기, 목록 쪽 나누기, 응답 조립(docs/credits-reviews.md 5절, 7절). DB를 모른다.
커서 형식은 common.cursor 한 곳이다(#973)."""

import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from common.cursor import encode_cursor
from common.errors import AppError


@dataclass(frozen=True)
class ReviewRow:
    """service가 읽은 후기 한 건 — 응답 조립에 필요한 칸만. user_id는 is_mine 판정에만 쓰고 응답에 싣지 않는다(결정 B)."""
    id: uuid.UUID
    user_id: str
    rating: int
    body: str
    created_at: datetime
    updated_at: datetime


def place_of(source: str, place_id: str | None) -> str:
    """핀이 가리키는 자체 DB 장소. 실시간 핀(source=live)이거나 장소가 없으면 422 PLACE_NOT_SUPPORTED — 후기를 붙일 곳이 없다."""
    if source == "live" or not place_id:
        raise AppError("PLACE_NOT_SUPPORTED")
    return place_id


def average(total: int, count: int) -> float | None:
    """평균 별점, 소수 첫째 자리(반올림은 0.05에서 올린다). 후기가 없으면 None."""
    if count == 0:
        return None
    return float((Decimal(total) / Decimal(count)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


def my_review(row: ReviewRow) -> dict:
    """MyReview 모양."""
    return {"id": str(row.id), "rating": row.rating, "body": row.body,
            "created_at": row.created_at, "updated_at": row.updated_at}


def review_item(row: ReviewRow, viewer_id: str) -> dict:
    """ReviewItem 모양 — 작성자는 is_mine으로만 알린다."""
    return {**my_review(row), "is_mine": row.user_id == viewer_id}


def page(rows: list[ReviewRow], *, viewer_id: str, page_size: int) -> tuple[list[dict], str | None]:
    """page_size + 1개까지 읽은 행으로 (items, next_cursor). 한 개 더 있으면 다음 쪽이 있다."""
    shown = rows[:page_size]
    items = [review_item(row, viewer_id) for row in shown]
    next_cursor = encode_cursor(shown[-1].created_at, shown[-1].id) if len(rows) > page_size else None
    return items, next_cursor
