"""docs/api-spec.yaml의 FeedbackRequest·FeedbackReceipt와 1:1. message 길이는 앞뒤 공백을 지운 뒤 service가 본다."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    category: Literal["bug", "idea", "other"] = "other"
    map_id: str | None = None


class FeedbackReceipt(BaseModel):
    id: str
    created_at: datetime
