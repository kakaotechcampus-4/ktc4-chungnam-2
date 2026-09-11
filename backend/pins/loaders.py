"""
authz.guard.require()가 쓸 리소스 로더. 리소스를 어떻게 읽는지는 pins만 아는 일이라(authz가
PinRow를 알면 의존 방향이 뒤집힌다), loader는 여기 pins가 정의하고 authz.guard는 이게 돌려준
Loaded(resource, obj)만 본다.

존재·비공개 판정은 pins 소유다(가드레일 1, 5-5-1) — authz가 아니라 여기서 끝낸다. 순서:
존재 확인(service.get_pin_or_404, 없으면 404 NOT_FOUND) → 비공개 판정(404 AI_PIN_PRIVATE) →
(이후 authz.guard가 구성원 여부를 404/403으로 분기).
"""

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Resource
from common.errors import AppError
from pins import service
from pins.deps import get_db_session
from pins.models import Pin as PinRow


@dataclass(frozen=True)
class LoadedPin:
    resource: Resource
    obj: Any  # PinRow — authz.guard.Loaded 프로토콜과 맞추는 이름(obj)


def load_pin(
    pinId: str = Path(...),
    db: Session = Depends(get_db_session),
    user: CurrentUser = Depends(get_current_user),
) -> LoadedPin:
    row: PinRow = service.get_pin_or_404(db, pinId)
    if row.visibility == "private" and row.created_by != user.user_id:
        raise AppError("AI_PIN_PRIVATE", "비공개 추천 후보입니다")
    return LoadedPin(
        resource=Resource(type="pin", map_id=row.map_id,   # ← URL이 아니라 읽은 행에서(authz Rule A)
                          author_id=row.created_by, kind=row.kind),
        obj=row,
    )
