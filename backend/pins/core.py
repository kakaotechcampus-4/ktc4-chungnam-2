"""
기능형 코어 — 순수 함수만 둔다(docs/code-quality.md). DB·시간·전역상태를 건드리지 않고,
입력을 받아 값을 반환할 뿐이라 모의 객체 없이 직접 호출해서 테스트한다.

pins → authz는 허용된 의존 방향(아래로만, docs/architecture.md 1절) — permissions 계산은
authz.core.permissions_for에 위임한다. pin_permissions(kind, is_member)는 여기서 삭제됐다
(#56 이관, mentor-review-plan.md) — authz/tests/test_permissions.py가 동등성을 보증한다.
"""

import re
from dataclasses import dataclass

from authz.core import Principal, Resource, permissions_for
from common import categories
from common.errors import AppError
from common.events import Event
from pins.schemas import (
    MemberFulfillment,
    Pin,
    PinCreateRequest,
    PlaceSource,
    Reaction,
    ReactionSummary,
)


LINK_PIN_REJECTED_MESSAGE = "링크로는 핀을 찍을 수 없어요. 이름으로 검색해 주세요"


COORDINATE_PIN_REJECTED_MESSAGE = "지도를 눌러 핀을 찍을 수는 없어요. 장소를 검색해서 골라 주세요"
CATEGORY_MISMATCH_MESSAGE = "고른 장소의 분류와 요청한 분류가 달라요"
KAKAO_ID_PREFIX = "kakao:"
KAKAO_PLACE_PAGE = "https://place.map.kakao.com/"
KAKAO_RAW_ID = re.compile(r"[0-9]{1,20}")


def validate_create(req: PinCreateRequest) -> None:
    """v1은 source=search 하나만 받는다(#191, #147). coordinate·link(link_url 포함)는 422 —
    스키마엔 v2 확장용으로 값이 남아 있어 여기서만 막는다. 좌표 범위·필수값은 스키마가 검증한다."""
    if req.source == "link" or req.link_url:
        raise AppError("VALIDATION_ERROR", LINK_PIN_REJECTED_MESSAGE)
    if req.source == "coordinate":
        raise AppError("VALIDATION_ERROR", COORDINATE_PIN_REJECTED_MESSAGE)


def validate_category_matches(requested: str, place_category: str) -> None:
    if requested != place_category:
        raise AppError("VALIDATION_ERROR", CATEGORY_MISMATCH_MESSAGE)


def kakao_place_url(kakao_place_id: str) -> str | None:
    """검색 결과 place_id("kakao:<id>")에서 카카오 장소 페이지 링크를 만든다. 요청에 URL 필드가 없고
    다른 소스(naver·google)의 ID에서는 만들 수 없으므로 그때는 None — 기록하지 않는다."""
    if not kakao_place_id.startswith(KAKAO_ID_PREFIX):
        return None
    raw = kakao_place_id[len(KAKAO_ID_PREFIX):]
    # 실제 카카오 장소 ID는 숫자뿐이다. 그 밖의 값(`../../x?y#z` 등)을 이어 붙이면 이 장소를 보는 모든
    # 사용자에게 오염된 링크가 나간다(#248) — 형식이 틀리면 매칭은 하되 ID·URL을 기록하지 않는다.
    return f"{KAKAO_PLACE_PAGE}{raw}" if KAKAO_RAW_ID.fullmatch(raw) else None


def is_duplicate(existing_place_ids: set[str], place_id: str | None) -> bool:
    """place_id가 없으면(좌표/링크 경로 중 장소 미확정) 중복 검사를 하지 않는다 — 목 서버와 동일.
    #33(중복 판정 기준) 확정 시 이 함수만 바꾸면 되도록 판정 로직을 여기 하나로 격리한다."""
    if place_id is None:
        return False
    return place_id in existing_place_ids


def is_visible_to(visibility: str, created_by: str, viewer_id: str) -> bool:
    """가드레일 1의 단일 판정 지점 — public이거나 본인이 만든 핀만 보인다."""
    return visibility == "public" or created_by == viewer_id


def kind_after_unconfirm(origin: str) -> str:
    """확정 리스트에서 뺄 때 되돌릴 kind — 저장하지 않고 origin에서 파생한다
    (docs/data-model.md: kind가 바뀌는 유일한 경로는 확정 추가/제외, origin은 불변).
    shortlist의 unconfirm flow가 쓴다(pins/api.py::unmark_confirmed)."""
    return "AI추천" if origin == "ai" else "일반"


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
    place_name: str | None = None
    place_url: str | None = None
    created_by_display_name: str | None = None
    checks: list[dict] | None = None
    reason: str | None = None
    member_fulfillment: dict | None = None
    place_source: dict | None = None
    my_reaction: Reaction | None = None


def to_pin_response(record: PinRecord, principal: Principal) -> Pin:
    """place_name·place_url·created_by_display_name·checks는 호출부가 채워 넘긴 값을 그대로 싣는다(각각
    places.api.get_places(자체 DB 이름·카카오 URL), auth.api.display_names, pins.checks 컬럼 — checks는 #57/#124 결정:
    게시 시점에 candidate.checks를 pins로 복사해두므로 여기서도 그 값을 그대로 옮긴다, 가드레일
    5 "게시된 뒤에도 유지"). price_bucket/source_run_id는 여전히 places·recommend 연동이 더
    필요해 채울 수 없다 — None으로 두면 라우터가 response_model_exclude_none으로 생략한다.
    permissions는 authz.core.permissions_for가 계산 — principal은 호출부(service.list_pins 등)가
    한 번만 만들어 그대로 내려보낸다(추가 멤버십 쿼리 없음)."""
    return Pin(
        id=record.id,
        map_id=record.map_id,
        category=record.category,
        kind=record.kind,
        visibility=record.visibility,
        lat=record.lat,
        lng=record.lng,
        place_name=record.place_name,
        place_url=record.place_url,
        created_by=record.created_by,
        created_by_display_name=record.created_by_display_name,
        checks=record.checks,
        reason=record.reason,
        member_fulfillment=MemberFulfillment(**record.member_fulfillment) if record.member_fulfillment else None,
        place_source=PlaceSource(**record.place_source) if record.place_source else None,
        my_reaction=record.my_reaction,
        reaction_summary=ReactionSummary(
            like=record.reaction_counts.like,
            neutral=record.reaction_counts.neutral,
            against=record.reaction_counts.against,
        ),
        permissions=permissions_for(
            principal,
            Resource(
                type="pin", map_id=record.map_id, author_id=record.created_by,
                kind=record.kind, category=record.category,
            ),
        ),
    )


def _public_pin_payload(pin: Pin) -> dict:
    """전체 채널로 나가는 페이로드 — my_reaction은 요청자 본인 것이라 싣지 않는다(가드레일 1)."""
    return pin.model_dump(exclude_none=True, exclude={"my_reaction"})


def pin_created_event(pin: Pin) -> Event | None:
    """docs/events.md pin.created. visibility='private'이면 발행하지 않는다(가드레일 1) —
    private 후보가 전체 채널로 새는 순간 「지도에 올리기」 전에 팀 전체가 보게 된다."""
    if pin.visibility == "private":
        return None
    return Event(map_id=pin.map_id, channel="public", type="pin.created", payload=_public_pin_payload(pin))


def pin_published_event(pin: Pin) -> Event | None:
    """docs/events.md pin.published — recommend의 「지도에 올리기」 전용(pin_created_event와
    페이로드는 같고 type만 다르다). 게시는 항상 public이라 private 분기는 없다(api.create_ai_pin이
    이미 visibility='public'으로 INSERT함) — 그래도 방어적으로 같은 체크를 유지한다."""
    if pin.visibility == "private":
        return None
    return Event(map_id=pin.map_id, channel="public", type="pin.published", payload=_public_pin_payload(pin))


def pin_deleted_event(pin_id: str, map_id: str, visibility: str) -> Event | None:
    """docs/events.md pin.deleted — 페이로드는 {pin_id}뿐이다. pin.created와 마찬가지로
    private 핀의 삭제 사실도 전체 채널로 새면 안 된다."""
    if visibility == "private":
        return None
    return Event(map_id=map_id, channel="public", type="pin.deleted", payload={"pin_id": pin_id})


# strip()이 못 잡는 폭 없는 문자(zero-width space·joiner·word joiner·BOM) — 눈에 안 보이는 사유를 막는다.
_INVISIBLE = dict.fromkeys(map(ord, "​‌‍⁠﻿"))


def reason_content(text: str | None) -> str | None:
    """공백·제로폭 문자만 있으면 None, 아니면 앞뒤 공백을 뗀 문자열. 사유가 "있는지" 판단하는 유일한 기준이다."""
    if not text or not text.translate(_INVISIBLE).strip():
        return None
    return text.strip()


def validate_reaction(reaction_type: str, reason_text: str | None, reason_chip_ids: list[str] | None) -> None:
    """가드레일 3 — 반대(against)는 사유가 필수다. 공백·제로폭만 있는 reason_text는 없는 것으로
    취급한다(목 서버는 이걸 놓쳐 "   "도 통과시키는 버그가 있다). 내용 없는 칩은 사유가 아니라
    요청 오류다(422 VALIDATION_ERROR — 반응 종류와 무관하게). like/neutral은 사유 없이 통과."""
    if any(reason_content(chip) is None for chip in reason_chip_ids or []):
        raise AppError("VALIDATION_ERROR", "reason_chip_ids에 내용 없는 칩이 있습니다")
    if reaction_type != "against":
        return
    if reason_content(reason_text) is None and not reason_chip_ids:
        raise AppError("EVIDENCE_REQUIRED", "반대 반응에는 사유가 필요합니다")


def validate_reactable(category: str) -> None:
    """반응 못 받는 카테고리(숙소·기타, #154, permissions.md)의 핀은 403이 아니라 422로 요청 자체를 거부.
    어떤 카테고리인지는 common/categories.py가 정한다(#280)."""
    if not categories.is_reactable(category):
        raise AppError("REACTION_NOT_ALLOWED")


def reaction_changed_event(
    pin_id: str, map_id: str, visibility: str, reaction_summary: ReactionSummary
) -> Event | None:
    """docs/events.md reaction.changed — 페이로드는 {pin_id, reaction_summary}. pin.created/
    pin.deleted와 같은 이유로 private 핀의 반응 변화도 전체 채널로 새면 안 된다(가드레일 1)."""
    if visibility == "private":
        return None
    return Event(
        map_id=map_id, channel="public", type="reaction.changed",
        payload={"pin_id": pin_id, "reaction_summary": reaction_summary.model_dump()},
    )
