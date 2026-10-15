"""카톡 대화 링크 일괄 핀 찍기(#577, 기획안 5-9) — 링크 미리보기와 핀 일괄 생성.

대화 내용은 서버로 오지 않는다(화면이 링크 URL만 뽑아 보낸다). 모델은 부르지 않는다.
URL·링크 좌표·장소 이름은 응답과 로그 어디에도 남기지 않는다 — 로그에는 개수와 에러 타입만 쓴다.
"""

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, wait

from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from authz.core import Principal
from common.errors import AppError
from common.ratelimit import SlidingWindowLimiter
from common.settings import settings
from places import api as places_api
from places.schemas import LinkParseResult
from pins import service
from pins.schemas import (
    BulkPinError, BulkPinItemResult, BulkPinResult, LinkPreviewItem, LinkPreviewResult, PinCreateRequest,
)

log = logging.getLogger("pingo.pins.link_import")

PREVIEW_WORKERS = 5          # 링크 해석 병렬 수
PREVIEW_DEADLINE_S = 15.0    # 요청 마감 — 넘긴 항목은 LINK_UNRESOLVED
link_preview_limiter = SlidingWindowLimiter(settings.pins_link_preview_per_min)   # 사용자당 URL 수 기준, 인메모리

_pin_request = TypeAdapter(PinCreateRequest)


def check_link_preview_rate(user_id: str, url_count: int) -> None:
    if not link_preview_limiter.allow(user_id, cost=url_count):
        raise AppError("RATE_LIMITED")


def _parse_one(url: str) -> LinkParseResult:
    return places_api.parse_link(url, db=None)   # 스레드마다 자체 세션(places가 연다)


def _already_pinned_pin_id(db: Session, map_id: str, result: LinkParseResult) -> str | None:
    """그 링크의 장소가 이 지도에 이미 핀으로 있으면 그 핀 id — #569와 같은 기준(pins.service의 판정 재사용)."""
    place_ids: list[str] = []
    for match in result.matches:
        if match.place_id.startswith("own:"):
            place_ids.append(match.place_id[len("own:"):])
        else:   # 기록된 카카오 ID — 그 ID로 매칭된 자체 DB 장소들
            place_ids.extend(c.place_id for c in places_api.own_places_by_kakao_id(match.place_id, db=db))
    for place_id in dict.fromkeys(place_ids):
        found = service._find_existing_pin_id(db, map_id, place_id) or service._find_live_pin_for_place(
            db, map_id, place_id, hint_kakao_id=result.kakao_place_id)
        if found is not None:
            return found
    if result.kakao_place_id:
        return service._find_existing_live_pin_id(db, map_id, result.kakao_place_id)
    return None


def preview_links(db: Session, map_id: str, urls: list[str]) -> LinkPreviewResult:
    """POST /maps/{mapId}/pins/link-preview — 쓰기 없음. 링크마다 parse_link를 스레드 5개로 병렬 실행하고 마감을 넘긴 항목은
    LINK_UNRESOLVED로 둔다. 항목 하나의 실패는 그 항목만 error다."""
    pool = ThreadPoolExecutor(max_workers=PREVIEW_WORKERS, thread_name_prefix="link-preview")
    futures: list[Future] = [pool.submit(_parse_one, url) for url in urls]
    wait(futures, timeout=PREVIEW_DEADLINE_S)
    pool.shutdown(wait=False, cancel_futures=True)   # 마감을 넘긴 해석은 기다리지 않는다(결과는 버린다)

    items: list[LinkPreviewItem] = []
    timed_out = 0
    for index, future in enumerate(futures):
        if not future.done():
            timed_out += 1
            items.append(LinkPreviewItem(index=index, status="error", error_code="LINK_UNRESOLVED"))
            continue
        exc = future.exception()
        if exc is None:
            result = future.result()
            items.append(LinkPreviewItem(
                index=index, status="ok", result=result, already_pinned_pin_id=_already_pinned_pin_id(db, map_id, result),
            ))
        elif isinstance(exc, AppError) and exc.code in ("LINK_NOT_SUPPORTED", "LINK_UNRESOLVED"):
            items.append(LinkPreviewItem(index=index, status="error", error_code=exc.code))
        else:   # 예기치 못한 실패 — 메시지·스택에는 URL이 실릴 수 있어 타입만 남긴다
            log.warning("link-preview 항목 해석 실패(%s)", type(exc).__name__)
            items.append(LinkPreviewItem(index=index, status="error", error_code="LINK_UNRESOLVED"))
    log.info("link-preview urls=%d ok=%d timed_out=%d", len(urls), sum(i.status == "ok" for i in items), timed_out)
    return LinkPreviewResult(items=items)


def _rejected(index: int, code: str, message: str | None = None, detail: dict | None = None) -> BulkPinItemResult:
    status = "duplicate" if code == "PIN_DUPLICATE" else "rejected"
    return BulkPinItemResult(index=index, status=status, error=BulkPinError(code=code, message=message, detail=detail))


def bulk_create_pins(db: Session, map_id: str, principal: Principal, raw_pins: list[dict]) -> BulkPinResult:
    """POST /maps/{mapId}/pins/bulk — 항목마다 기존 핀 생성(service.create_pin)을 SAVEPOINT로 감싸 재사용한다.
    한 항목의 실패는 그 SAVEPOINT만 되돌리고(db.rollback() 금지 — 앞 항목이 날아간다) 나머지는 만든다. 커밋은 호출자(요청 끝) 한 번."""
    results: list[BulkPinItemResult] = []
    for index, raw in enumerate(raw_pins):
        try:
            req = _pin_request.validate_python(raw)
        except ValidationError:
            results.append(_rejected(index, "VALIDATION_ERROR", "핀 요청 형식이 맞지 않아요"))
            continue
        try:
            with db.begin_nested():
                pin = service.create_pin(db, map_id, principal, req, isolated=True)
        except AppError as exc:
            results.append(_rejected(index, exc.code, exc.message, exc.detail))
            continue
        results.append(BulkPinItemResult(index=index, status="created", pin=pin))
    log.info("bulk pins=%d created=%d", len(raw_pins), sum(r.status == "created" for r in results))
    return BulkPinResult(results=results)
