"""docs/api-spec.yaml credits 태그(CreditBalance, CreditAd, AdSession, AdClaim)와 1:1."""

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class CreditPrices(BaseModel):
    recommend_run: int = Field(ge=0)
    course: int = Field(ge=0)


class CreditAd(BaseModel):
    """광고 보고 충전(명세 3.7). 화면은 available만 보고 버튼을 띄운다."""

    available: bool
    reward: int = Field(ge=0)
    used_today: int = Field(ge=0)
    daily_max: int = Field(ge=0)
    provider: Literal["fake", "adsense", "gpt"] | None
    unit_id: str | None


class CreditBalance(BaseModel):
    balance: int = Field(ge=0)
    max_balance: int = Field(ge=0)
    prices: CreditPrices
    review_reward: int = Field(ge=0)
    ad: CreditAd


class AdSession(BaseModel):
    ad_session_id: uuid.UUID
    claim_after_s: int = Field(ge=0)


class AdClaim(BaseModel):
    credited: int = Field(ge=0)
    balance: int = Field(ge=0)
