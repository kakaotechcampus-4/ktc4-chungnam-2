"""docs/api-spec.yaml의 places 태그 — GET /places/search (#180).

로그인만 필요하고 지도 구성원 여부는 보지 않는다. 검증(422) → 호출 상한(429) → 검색(503) 순서다.
"""

from fastapi import APIRouter, Depends, Query

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.errors import AppError
from places import api
from places.schemas import PlaceSearchResult

router = APIRouter(tags=["places"])

_MAX_QUERY_LEN = 50


@router.get("/places/search", response_model=list[PlaceSearchResult], response_model_exclude_none=True)
def search_places(
    q: str = Query(...),
    lat: float | None = Query(default=None, ge=-90, le=90),
    lng: float | None = Query(default=None, ge=-180, le=180),
    limit: int = Query(default=10, ge=1, le=15),
    user: CurrentUser = Depends(get_current_user),
):
    query = q.strip()
    if not 1 <= len(query) <= _MAX_QUERY_LEN:
        raise AppError("VALIDATION_ERROR", f"검색어는 앞뒤 공백을 뺀 1~{_MAX_QUERY_LEN}자여야 합니다")
    if (lat is None) != (lng is None):
        raise AppError("VALIDATION_ERROR", "lat과 lng는 함께 보내야 합니다")
    api.check_search_rate(user.user_id)
    near = (lat, lng) if lat is not None and lng is not None else None
    return api.search_by_name(query, near, limit)
