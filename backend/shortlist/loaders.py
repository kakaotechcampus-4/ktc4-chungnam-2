"""
authz.guard.require_with_principal()이 쓸 리소스 로더(pins/loaders.py와 같은 패턴).

POST /maps/{mapId}/shortlist는 mapId를 경로에서, pin_id를 바디에서 따로 받는다 — 이 둘이
다른 지도를 가리킬 수 있다(authz Rule B, mentor-review-plan.md "authz 교차-지도 위험"). 여기서
실제로 읽은 핀의 map_id와 경로 mapId를 대조해 다르면 authz.core.can()을 부르기도 전에
404로 끝낸다. 존재·가시성 판정도 pins 소유라 pins.api를 통해 여기서 끝낸다
(pins/loaders.py::load_pin과 같은 원칙 — authz는 PinRow를 모른다).
"""

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Resource
from common.errors import AppError
from pins import api as pins_api
from shortlist import service
from shortlist.deps import get_db_session
from shortlist.schemas import ShortlistAddRequest


@dataclass(frozen=True)
class LoadedPinForConfirm:
    resource: Resource
    obj: Any  # pins.models.Pin


def load_pin_for_confirm(
    body: ShortlistAddRequest,
    mapId: str = Path(...),
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(get_current_user),
) -> LoadedPinForConfirm:
    pin_row = pins_api.get_pin_for_viewer(db, pin_id=body.pin_id, viewer_id=user.user_id)
    if pin_row.map_id != mapId:
        raise AppError("NOT_FOUND")  # Rule B — 경로/바디 불일치는 authz를 부르기 전에 끝낸다
    if pin_row.visibility == "private":
        # 가드레일 1 — 본인 소유 비공개 AI 후보도 「지도에 올리기」 없이 곧장 전체 공개
        # 확정 리스트로 승격시킬 수 없다(for_Root.md 별도 보고).
        raise AppError("AI_PIN_PRIVATE")
    return LoadedPinForConfirm(
        resource=Resource(type="pin", map_id=pin_row.map_id, author_id=pin_row.created_by, kind=pin_row.kind),
        obj=pin_row,
    )


@dataclass(frozen=True)
class LoadedShortlistItem:
    resource: Resource
    obj: Any  # shortlist.models.ShortlistItem


def load_shortlist_item(
    itemId: str = Path(...),
    db: Session = Depends(get_db_session),
) -> LoadedShortlistItem:
    row = service.get_item_or_404(db, itemId)
    # row.map_id가 실제로 읽은 행에서 나오므로(Rule A) 여기엔 Rule B 문제가 없다 — 경로에
    # mapId 자체가 없다(DELETE /shortlist/{itemId}, mentor-review-plan.md 검증 절 확인).
    return LoadedShortlistItem(resource=Resource(type="shortlist_item", map_id=row.map_id), obj=row)
