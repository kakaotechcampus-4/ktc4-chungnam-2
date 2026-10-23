"""
docs/api-spec.yaml `notifications` 태그 4개 엔드포인트. 권한은 로그인만이다 — 지도 구성원 여부를 보지 않는다
(나간 지도의 알림도 남고, 알림은 `/me/*`라 mapId가 없다). 그래서 authz 가드 없이 get_current_user만 건다.
"""

from fastapi import APIRouter, Depends, Query, Response

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from notifications import service
from notifications.deps import DbSession
from notifications.schemas import (
    NotificationList,
    NotificationPrefs,
    NotificationPrefsUpdate,
    NotificationReadRequest,
)

router = APIRouter(tags=["notifications"], dependencies=[Depends(get_current_user)])


@router.get("/me/notifications", response_model=NotificationList, response_model_exclude_none=True)
def get_notifications(
    limit: int = Query(20, ge=1, le=50),
    before: str | None = Query(None),
    unread_only: bool = Query(False),
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    return service.list_notifications(db, user_id=user.user_id, limit=limit, before=before, unread_only=unread_only)


@router.post("/me/notifications/read", status_code=204)
def post_notifications_read(
    body: NotificationReadRequest | None = None,
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    service.mark_read(db, user_id=user.user_id, ids=body.ids if body else None)
    return Response(status_code=204)


@router.get("/me/notification-prefs", response_model=NotificationPrefs)
def get_notification_prefs(user: CurrentUser = Depends(get_current_user), db=DbSession):
    return service.get_prefs(db, user_id=user.user_id)


@router.put("/me/notification-prefs", response_model=NotificationPrefs)
def put_notification_prefs(
    body: NotificationPrefsUpdate,
    user: CurrentUser = Depends(get_current_user),
    db=DbSession,
):
    return service.update_prefs(db, user_id=user.user_id, updates=[(p.type, p.enabled) for p in body.prefs])
