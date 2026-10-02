"""docs/api-spec.yaml의 places 태그 — GET /places/search (#180).

로그인만 필요하고 지도 구성원 여부는 보지 않는다. 검증(422) → 호출 상한(429) → 검색(503) 순서다.
"""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import get_db_session
from common.errors import AppError
from places import api
from places.schemas import PlaceHint, PlaceSearchResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["places"])

_MAX_QUERY_LEN = 50


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
    results = api.search_by_name(query, near, limit)
    _fill_pinnable(results, db)
    return results


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
