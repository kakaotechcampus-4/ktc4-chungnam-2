"""SSE 엔드포인트 2개(전체/개인) — docs/events.md 전달 명세, docs/api-spec.yaml realtime 태그.
개인 채널은 반드시 인증된 본인 user_id로만 구독한다(realtime/CLAUDE.md "가장 중요한 테스트").
"""

import json

from fastapi import APIRouter, Depends, Header, Path, Request
from fastapi.responses import StreamingResponse

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import SessionLocal
from common.events import EventLog
from realtime import service
from realtime.dispatcher import dispatcher

router = APIRouter(tags=["realtime"], dependencies=[Depends(get_current_user)])


def _parse_last_event_id(raw: str | None) -> int | None:
    """잘못된 헤더는 '재전송 없이 지금부터 시작'으로 취급한다 — 400을 내서 연결 자체를
    막을 이유는 없다(재연결 기능이 하나 빠질 뿐 나머지는 정상 동작해야 한다)."""
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _sse_format(row: EventLog) -> str:
    data = json.dumps({"type": row.type, "map_id": row.map_id, "payload": row.payload})
    return f"id: {row.seq}\nevent: {row.type}\ndata: {data}\n\n"


def _sse_control_event(type_: str) -> str:
    return f"event: control\ndata: {json.dumps({'type': type_})}\n\n"


@router.get("/maps/{mapId}/events")
async def public_events(
    request: Request,
    mapId: str = Path(...),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    after_seq = _parse_last_event_id(last_event_id)

    async def gen():
        if after_seq is not None:
            # 요청 스코프 db를 이 무기한 제너레이터 안까지 들고 있으면 SSE 연결이 살아있는 내내
            # 커넥션 풀에서 세션 하나를 붙들어맨다. 재전송 조회 하나만 짧게 쓰고 바로 닫는다.
            with SessionLocal() as db:
                result = service.replay(db, mapId, after_seq, "public")
            if result.truncated:
                yield _sse_control_event("replay_truncated")
            for row in result.rows:
                yield _sse_format(row)
        sub = dispatcher.subscribe(mapId, channel="public")
        try:
            while not await request.is_disconnected():
                row = await sub.queue.get()
                yield _sse_format(row)   # Subscription.wants()가 이미 dispatcher._tick에서 걸러줌
        finally:
            dispatcher.unsubscribe(mapId, sub)

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/maps/{mapId}/events/me")
async def private_events(
    request: Request,
    mapId: str = Path(...),
    user: CurrentUser = Depends(get_current_user),
    last_event_id: str | None = Header(None, alias="Last-Event-ID"),
):
    """개인 채널 — public_events와 같은 구조, channel="private"·user_id만 다르다."""
    after_seq = _parse_last_event_id(last_event_id)

    async def gen():
        if after_seq is not None:
            with SessionLocal() as db:
                result = service.replay(db, mapId, after_seq, "private")
            if result.truncated:
                yield _sse_control_event("replay_truncated")
            for row in result.rows:
                if row.recipient_user_id == user.user_id:
                    yield _sse_format(row)
        sub = dispatcher.subscribe(mapId, channel="private", user_id=user.user_id)
        try:
            while not await request.is_disconnected():
                row = await sub.queue.get()
                yield _sse_format(row)
        finally:
            dispatcher.unsubscribe(mapId, sub)

    return StreamingResponse(gen(), media_type="text/event-stream")
