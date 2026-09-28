"""
docs/api-spec.yaml의 shortlist 태그 스키마와 1:1. Pin은 pins.schemas가 소유(#56 전면 이관
전까지)하고 Permissions는 authz.schemas가 소유한다 — 이 모듈은 둘 다 그대로 가져다 쓴다.
"""

from pydantic import BaseModel

from authz.schemas import Permissions
from pins.schemas import Pin


class ShortlistAddRequest(BaseModel):
    pin_id: str


class ShortlistItem(BaseModel):
    id: str
    pin: Pin
    visit_order: int | None = None
    added_by: str
    permissions: Permissions


class RouteLeg(BaseModel):
    from_pin_id: str
    to_pin_id: str
    distance_m: float
    approx_minutes: int


class Route(BaseModel):
    region_label: str
    ordered_pin_ids: list[str]
    total_distance_m: float
    legs: list[RouteLeg]
