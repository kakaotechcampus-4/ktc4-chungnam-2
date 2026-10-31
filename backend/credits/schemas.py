"""docs/api-spec.yaml credits 태그(CreditBalance)와 1:1."""

from pydantic import BaseModel, Field


class CreditPrices(BaseModel):
    recommend_run: int = Field(ge=0)
    course: int = Field(ge=0)


class CreditBalance(BaseModel):
    balance: int = Field(ge=0)
    prices: CreditPrices
    review_reward: int = Field(ge=0)
