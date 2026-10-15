"""docs/api-spec.yaml의 places 태그 — GET /places/search (#180), POST /places/from-link (#474).

로그인만 필요하고 지도 구성원 여부는 보지 않는다. 검증(422) → 호출 상한(429) → 검색(503) 순서다.
"""

import logging
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import get_db_session
from common.errors import AppError
from common import categories
from places import api, logguard
from places.schemas import LinkParseResult, PlaceHint, PlaceSearchResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["places"])
logguard.install()   # /places/nearest의 좌표가 uvicorn 접근 로그에 남지 않게 한다(#473)

class LinkParseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2000)


_MAX_QUERY_LEN = 50
_FETCH_LIMIT = 15   # limit(최대 15)과 같다 — 카카오에서 이만큼 받아 정렬한 뒤 limit으로 자른다(#488)


@router.get("/places/search", response_model=list[PlaceSearchResult], response_model_exclude_none=True)
def search_places(
    q: str = Query(...),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=10, ge=1, le=15),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    query = q.strip()
    if not 1 <= len(query) <= _MAX_QUERY_LEN:
        raise AppError("VALIDATION_ERROR", f"검색어는 앞뒤 공백을 뺀 1~{_MAX_QUERY_LEN}자여야 합니다")
    if (lat is None) != (lng is None):
        raise AppError("VALIDATION_ERROR", "lat과 lng는 함께 보내야 합니다")
    api.check_search_rate(user.user_id)
    near = (lat, lng) if lat is not None and lng is not None else None
    results = api.search_by_name(query, near, _FETCH_LIMIT)
    _fill_pinnable(results, db)
    return _own_db_first(results)[:limit]


@router.get("/places/nearest", response_model=list[PlaceSearchResult], response_model_exclude_none=True)
def nearest_places(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    category: Literal[categories.all_categories()] | None = Query(default=None),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """지도를 눌러 핀(#473) — 누른 좌표는 이 요청 안에서만 쓴다. 저장·로깅하지 않는다(예외 경로에도 좌표를 싣지 않는다)."""
    api.check_search_rate(user.user_id)   # GET /places/search와 같은 상한(같은 버킷)
    try:
        return api.nearest_own_places(lat, lng, category, db=db)
    except SQLAlchemyError as exc:
        logger.warning("nearest 조회 실패(%s)", type(exc).__name__)   # 타입만 — SQL 파라미터에 좌표가 실린다
        raise AppError("PLACES_UNAVAILABLE") from None


@router.post("/places/from-link", response_model=LinkParseResult, response_model_exclude_none=True)
def parse_link(
    body: LinkParseRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db_session),
):
    """지도 링크 해석(#474) — 422 → 429 → 해석. 핀을 만들지 않고 아무것도 저장하지 않는다."""
    api.check_link_rate(user.user_id)
    return api.parse_link(body.url, db=db)


def _own_db_first(results: list[PlaceSearchResult]) -> list[PlaceSearchResult]:
    """자체 DB 짝이 있는 결과(pinnable=true)를 앞으로 올린다(#488). 그룹 안은 카카오가 준 순서 그대로(안정 정렬).
    카카오가 준 후보 안에서만 고르고, pinnable 계산이 생략됐으면(None이 하나라도) 원래 순서를 둔다."""
    if any(r.pinnable is None for r in results):
        return results
    return sorted(results, key=lambda r: not r.pinnable)


def _fill_pinnable(results: list[PlaceSearchResult], db: Session) -> None:
    """결과마다 자체 DB에 짝이 있는지(#238) 한 번의 쿼리로 읽기만 해서 채운다 — 카카오 ID를 기록하지 않는다.
    자체 DB를 못 읽으면 검색은 살리고 pinnable만 생략한다(스펙상 optional, FE는 true로 본다)."""
    if not results:
        return
    hints = [PlaceHint(r.place_id, r.place_name, r.lat, r.lng, r.category or "") for r in results]
    try:
        flags = api.pinnable_flags(hints, db=db)
    except SQLAlchemyError as exc:
        # 예외 타입만 남긴다 — 메시지·스택에는 SQL 파라미터(카카오가 준 이름·좌표)가 실린다(#53)
        logger.warning("pinnable 계산 실패(%s) — 생략한다", type(exc).__name__)
        return
    for r, ok in zip(results, flags):
        r.pinnable = ok
