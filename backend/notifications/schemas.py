"""docs/api-spec.yaml notifications 태그 스키마와 1:1."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

NotificationType = Literal["pin_reaction", "member_joined", "owner_changed", "map_deleted"]


class Notification(BaseModel):
    id: str
    type: NotificationType
    map_id: str
    map_title: str | None = None
    pin_id: str | None = None
    message: str
    created_at: datetime
    read: bool


class NotificationList(BaseModel):
    items: list[Notification]
    unread_count: int = Field(ge=0)
    next_before: str | None = None


class NotificationReadRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[str] | None = Field(default=None, max_length=100)


class NotificationPref(BaseModel):
    type: NotificationType
    enabled: bool


class NotificationPrefs(BaseModel):
    prefs: list[NotificationPref]


class NotificationPrefsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prefs: list[NotificationPref] = Field(min_length=1)
