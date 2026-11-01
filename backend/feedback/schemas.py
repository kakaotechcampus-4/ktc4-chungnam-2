"""docs/api-spec.yaml의 FeedbackRequest·FeedbackReceipt와 1:1. message는 원문 1~1000자(스펙)이고, 앞뒤 공백을 지운 뒤의 길이는 service가 다시 본다."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=1000)   # 스펙과 같은 원문 길이 제약(#733). 공백만 있는 글은 service가 지운 뒤 거른다
    category: Literal["bug", "idea", "other"] = "other"
    map_id: str | None = None


class FeedbackReceipt(BaseModel):
    id: str
    created_at: datetime
