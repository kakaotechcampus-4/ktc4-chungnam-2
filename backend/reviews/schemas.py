"""docs/api-spec.yaml reviews 태그(ReviewUpsertRequest, MyReview, ReviewItem, ReviewPage, ReviewSaved)와 1:1.

작성자 이름·id 필드는 없다(#432 결정 B) — 화면은 is_mine으로 「나」/「핑고 사용자」를 고른다.
요청 제약은 스펙과 같아야 한다(integration/test_request_constraints_match_spec.py).
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

from reviews.constants import RATING_MAX, RATING_MIN, REVIEW_BODY_MAX

Rating = Annotated[int, Field(ge=RATING_MIN, le=RATING_MAX)]


class ReviewUpsertRequest(BaseModel):
    # strict — 4.0, "4", true를 별점으로 받지 않는다(스펙은 정수)
    rating: Annotated[int, Field(ge=RATING_MIN, le=RATING_MAX, strict=True)]
    # 앞뒤 공백을 걷은 뒤 길이를 본다 — 공백뿐인 글은 422
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=REVIEW_BODY_MAX)]


class MyReview(BaseModel):
    id: str
    rating: Rating
    body: str
    created_at: datetime
    updated_at: datetime


class ReviewItem(MyReview):
    is_mine: bool


class ReviewSummary(BaseModel):
    average_rating: float | None   # 숨김 제외 평균, 소수 첫째 자리. 후기가 없으면 null(필드는 늘 있다)
    count: int = Field(ge=0)


class ReviewLimits(BaseModel):
    body_max: int


class ReviewPage(BaseModel):
    summary: ReviewSummary
    limits: ReviewLimits
    mine: MyReview | None = None       # 없으면 필드를 뺀다(라우터가 exclude_unset)
    items: list[ReviewItem]
    next_cursor: str | None = None     # 없으면 필드를 뺀다


class ReviewSaved(BaseModel):
    review: MyReview
    credited: int = Field(ge=0)
    balance: int = Field(ge=0)
