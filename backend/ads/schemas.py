"""docs/api-spec.yaml ads 태그(AdPlace, Ad, AdList, AdClickRequest)와 1:1."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from ads.constants import AD_SLOTS
from common import categories

Category = Literal[categories.recommendable()]  # 스펙의 RecommendCategory(common/categories.py, #280)


class AdPlace(BaseModel):
    place_id: str
    name: str = Field(max_length=100)
    category: Category
    address: str | None = Field(default=None, max_length=200)
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    place_url: str | None = Field(default=None, max_length=2000)


class Ad(BaseModel):
    """광고 칸 하나. 이유, 조건별 충족 체크, 구성원 충족 집계, 메모, 집계 값은 없다."""

    ad_id: str
    place: AdPlace
    on_map: bool


class AdList(BaseModel):
    ads: list[Ad] = Field(max_length=AD_SLOTS)


class AdClickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    map_id: str = Field(min_length=1)   # 권한 확인용. 저장하지 않는다
