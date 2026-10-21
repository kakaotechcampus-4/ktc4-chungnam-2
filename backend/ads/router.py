"""
docs/api-spec.yaml `ads` 태그 — 추천 탭 광고 조회와 클릭 기록(docs/ads.md 7절).

인가는 여기서 분기하지 않는다(authz.guard, docs/permissions.md). 둘 다 새 권한 액션 없이 구성원 확인만 한다.
- GET 광고: require_map_member() — 조회 전용 GET의 관례
- POST 클릭: 지도가 경로가 아니라 본문(map_id)에 있다. 그래서 require_map_member()가 돌려주는 의존성 함수를 본문의 map_id로
  직접 부른다(recommend/flows.py가 require()를 직접 부르는 것과 같은 방식 — resolve_principal은 여전히 guard 안에서만 불린다).
  구성원 확인이 먼저다. 비구성원과 없는 광고는 둘 다 404라 어느 쪽인지 드러나지 않는다.
"""

import random
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.orm import Session

from ads import service
from ads.schemas import AdClickRequest, AdList, Category
from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Principal
from authz.deps import get_membership_gateway
from authz.guard import require_map_member
from authz.ports import MembershipGateway
from common.database import get_db_session

router = APIRouter(tags=["ads"], dependencies=[Depends(get_current_user)])

AdsForMap = Depends(require_map_member())
DbSession = Depends(get_db_session)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_rng() -> random.Random:
    """광고 고르기용 랜덤. 테스트는 시드를 준 Random으로 바꾼다."""
    return random.Random()


@router.get("/maps/{mapId}/ads", response_model=AdList)
def get_ads(
    response: Response,
    mapId: str = Path(...),
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    category: Category | None = Query(default=None),
    principal: Principal = AdsForMap,
    db: Session = DbSession,
    rng: random.Random = Depends(get_rng),
):
    """조회 1회 = 실린 광고마다 노출 1회(served_count, 같은 트랜잭션). 응답을 캐시하지 않는다."""
    response.headers["Cache-Control"] = "no-store"
    ads = service.list_ads(db, map_id=mapId, user_id=principal.user_id, category=category, center=(lat, lng),
                           now=_now(), rng=rng)
    return {"ads": ads}


@router.post("/ads/{adId}/clicks", status_code=204)
def post_ad_click(
    body: AdClickRequest,
    adId: str = Path(...),
    user: CurrentUser = Depends(get_current_user),
    gateway: MembershipGateway = Depends(get_membership_gateway),
    db: Session = DbSession,
):
    require_map_member()(mapId=body.map_id, user=user, gateway=gateway)   # 비구성원 404
    service.record_click(db, ad_id=adId, now=_now())
