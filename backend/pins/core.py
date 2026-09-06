"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시간·전역상태를 건드리지 않고,
입력을 받아 값을 반환할 뿐이라 모의 객체 없이 직접 호출해서 테스트한다.
"""

from dataclasses import dataclass

from pins.errors import PinError
from pins.schemas import Permissions, Pin, PinCreateRequest, PinSource, ReactionSummary


def resolve_source(req: PinCreateRequest) -> PinSource:
    """source가 명시되지 않으면 어떤 필드가 왔는지로 추론한다. 결정 불가·모순이면 422."""
    if req.source is not None:
        return req.source

    provided: list[PinSource] = []
    if req.link_url:
        provided.append("link")
    if req.place_id:
        provided.append("search")
    if req.lat is not None and req.lng is not None:
        provided.append("coordinate")

    if len(provided) == 0:
        raise PinError(
            422,
            "VALIDATION_ERROR",
            "핀 생성 경로를 알 수 없습니다 — link_url, place_id, lat+lng 중 하나가 필요합니다",
        )
    if len(provided) > 1:
        raise PinError(
            422,
            "VALIDATION_ERROR",
            "여러 경로의 값이 동시에 왔습니다 — source를 명시해주세요",
        )
    return provided[0]


def validate_create(req: PinCreateRequest) -> PinSource:
    """경로별 필수값과 좌표 범위를 검증하고, 확정된 source를 반환한다."""
    source = resolve_source(req)

    if source == "link" and not req.link_url:
        raise PinError(422, "VALIDATION_ERROR", "link 경로에는 link_url이 필요합니다")
    if source == "search" and not req.place_id:
        raise PinError(422, "VALIDATION_ERROR", "search 경로에는 place_id가 필요합니다")
    if source == "coordinate":
        if req.lat is None or req.lng is None:
            raise PinError(422, "VALIDATION_ERROR", "coordinate 경로에는 lat, lng가 모두 필요합니다")
        if not (-90 <= req.lat <= 90):
            raise PinError(422, "VALIDATION_ERROR", "lat은 -90~90 범위여야 합니다")
        if not (-180 <= req.lng <= 180):
            raise PinError(422, "VALIDATION_ERROR", "lng는 -180~180 범위여야 합니다")

    return source


def is_duplicate(existing_place_ids: set[str], place_id: str | None) -> bool:
    """place_id가 없으면(좌표/링크 경로 중 장소 미확정) 중복 검사를 하지 않는다 — 목 서버와 동일.
    #33(중복 판정 기준) 확정 시 이 함수만 바꾸면 되도록 판정 로직을 여기 하나로 격리한다."""
    if place_id is None:
        return False
    return place_id in existing_place_ids


def is_visible_to(visibility: str, created_by: str, viewer_id: str) -> bool:
    """가드레일 1의 단일 판정 지점 — public이거나 본인이 만든 핀만 보인다."""
    return visibility == "public" or created_by == viewer_id


def pin_permissions(kind: str, is_member: bool) -> Permissions:
    """docs/permissions.md member.actions + 9/4 결정(#25 핀 삭제는 구성원 누구나)을 반영한다.
    비구성원이면 전부 False. can_disable은 evidence_line 전용이라 여기서 다루지 않는다."""
    return Permissions(
        can_react=is_member,
        can_revert=is_member,
        can_delete=is_member,
        can_add_to_shortlist=is_member and kind != "확정",
        can_remove_from_shortlist=is_member and kind == "확정",
    )


@dataclass(frozen=True)
class ReactionCounts:
    like: int = 0
    neutral: int = 0
    against: int = 0


@dataclass(frozen=True)
class PinRecord:
    """ORM 행에서 응답 조립에 필요한 값만 추린 것 — core가 SQLAlchemy를 몰라도 되게 한다."""

    id: str
    map_id: str
    category: str
    kind: str
    visibility: str
    lat: float
    lng: float
    created_by: str
    reaction_counts: ReactionCounts


def to_pin_response(record: PinRecord, viewer_id: str, is_member: bool) -> Pin:
    """place_name/price_bucket/created_by_display_name/checks/source_run_id는 places·maps·recommend가
    없어 채울 수 없다 — None으로 두면 라우터가 response_model_exclude_none으로 생략한다."""
    return Pin(
        id=record.id,
        map_id=record.map_id,
        category=record.category,
        kind=record.kind,
        visibility=record.visibility,
        lat=record.lat,
        lng=record.lng,
        created_by=record.created_by,
        reaction_summary=ReactionSummary(
            like=record.reaction_counts.like,
            neutral=record.reaction_counts.neutral,
            against=record.reaction_counts.against,
        ),
        permissions=pin_permissions(record.kind, is_member),
    )


def pin_created_event(pin: Pin) -> tuple[str, str, dict] | None:
    """docs/events.md pin.created. visibility='private'이면 발행하지 않는다(가드레일 1) —
    private 후보가 전체 채널로 새는 순간 「지도에 올리기」 전에 팀 전체가 보게 된다."""
    if pin.visibility == "private":
        return None
    return ("public", "pin.created", pin.model_dump(exclude_none=True))


def pin_deleted_event(pin_id: str, visibility: str) -> tuple[str, str, dict] | None:
    """docs/events.md pin.deleted — 페이로드는 {pin_id}뿐이다. pin.created와 마찬가지로
    private 핀의 삭제 사실도 전체 채널로 새면 안 된다."""
    if visibility == "private":
        return None
    return ("public", "pin.deleted", {"pin_id": pin_id})
