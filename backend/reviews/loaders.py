"""
authz.guard.require()가 쓸 핀 로더(shortlist/loaders.py와 같은 모양). 후기 경로는 핀으로 부르고(#432 D1) 권한은 그 핀의 지도
구성원이다 — 핀 조회(GET /pins/{pinId}/reactions)와 같은 규칙으로 비구성원은 404다.

핀이 있는지는 pins 소유라 pins.api.get_pin_for_viewer로 여기서 끝낸다(없거나 지운 핀은 404). 구성원 판정은 이 로더가 아니라
authz.guard가 읽은 핀의 map_id로 한다(authz Rule A).
"""

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Resource
from common.database import get_db_session
from pins import api as pins_api


@dataclass(frozen=True)
class LoadedReviewPin:
    resource: Resource
    obj: Any  # pins.api.PinRef


def load_review_pin(
    pinId: str = Path(...),
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(get_current_user),
) -> LoadedReviewPin:
    pin = pins_api.get_pin_for_viewer(db, pin_id=pinId, viewer_id=user.user_id)
    return LoadedReviewPin(
        resource=Resource(type="pin", map_id=pin.map_id, author_id=pin.created_by, kind=pin.kind),
        obj=pin,
    )
