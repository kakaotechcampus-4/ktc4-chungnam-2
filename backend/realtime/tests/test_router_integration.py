"""public_events/private_events의 SSE 제너레이터를 직접 구동하는 통합 테스트.
StreamingResponse를 실제 HTTP 스트림으로 굳이 열지 않고 async generator만 떼어 테스트한다
(TestClient의 스레드 기반 스트리밍은 백그라운드 폴링 태스크와 얽혀 테스트를 불안정하게 만든다).

실제 PostgreSQL 필요(docker-compose up -d). router.py가 SessionLocal을 직접 쓰므로
(요청 스코프 DI가 아니라 — 재전송은 짧은 세션 하나만 쓰기 위해서, mentor-review-plan.md 참고)
여기서는 realtime.router.SessionLocal을 테스트 DB로 monkeypatch한다.
"""

import asyncio

import pytest

import realtime.router as router_module
from auth.schemas import CurrentUser
from common.events import EventLog
from realtime.dispatcher import dispatcher
from realtime.router import private_events, public_events


class _FakeRequest:
    def __init__(self):
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1   # 첫 호출(구독 직후)엔 살아있다고 답하고, 그다음엔 끊겼다고 답한다


@pytest.fixture(autouse=True)
def _patch_session_local(db_session, monkeypatch):
    """router.py의 SessionLocal()을 테스트 트랜잭션(db_session)을 감싸는 팩토리로 바꾼다."""

    def _factory():
        class _Ctx:
            def __enter__(self_inner):
                return db_session

            def __exit__(self_inner, *exc):
                return False

        return _Ctx()

    monkeypatch.setattr(router_module, "SessionLocal", _factory)


@pytest.mark.asyncio
async def test_public_events_replays_then_streams_live_event(db_session):
    old = EventLog(map_id="int-map", channel="public", type="pin.created", payload={"n": 1})
    db_session.add(old)
    db_session.flush()
    after_seq = old.seq

    request = _FakeRequest()
    response = await public_events(request=request, mapId="int-map", last_event_id=str(after_seq))
    agen = response.body_iterator

    # 실시간 tail에 새 이벤트가 하나 들어올 것 — subscribe 이후에 넣어야 구독자가 받는다.
    async def _emit_live_event_soon():
        await asyncio.sleep(0.05)
        live = EventLog(map_id="int-map", channel="public", type="pin.reacted", payload={"n": 2})
        for sub in dispatcher._subscribers.get("int-map", []):
            if sub.wants(live):
                sub.queue.put_nowait(live)

    emitter = asyncio.create_task(_emit_live_event_soon())
    try:
        chunk = await asyncio.wait_for(agen.__anext__(), timeout=1)
        assert "pin.reacted" in chunk
    finally:
        await emitter
        with pytest.raises(StopAsyncIteration):
            await asyncio.wait_for(agen.__anext__(), timeout=1)


@pytest.mark.asyncio
async def test_private_events_never_leaks_other_users_row(db_session):
    """재전송 단계뿐 아니라 실시간 tail 단계에서도 다른 사람의 private 이벤트가 새면 안 된다
    (realtime/CLAUDE.md "가장 중요한 테스트"). is_disconnected()가 계속 False를 주는 동안
    generator는 자기 큐에 뭔가 들어올 때까지 블록되므로, 여기서는 다른 사람 몫 이벤트를 먼저
    흘려보낸 뒤 본인 몫 이벤트를 넣어 그것만 받는지 확인한다."""
    old_row = EventLog(
        map_id="int-map2", channel="private", type="ai.recommendation.ready",
        payload={"secret": True}, recipient_user_id="user-a",
    )
    db_session.add(old_row)
    db_session.flush()

    class _NeverDisconnects:
        async def is_disconnected(self) -> bool:
            return False

    request = _NeverDisconnects()
    user = CurrentUser(user_id="user-b")   # 다른 사람
    response = await private_events(
        request=request, mapId="int-map2", user=user, last_event_id=str(old_row.seq - 1)
    )
    agen = response.body_iterator

    async def _emit_wrong_then_right_recipient():
        await asyncio.sleep(0.05)
        wrong = EventLog(map_id="int-map2", channel="private", type="x", payload={},
                         recipient_user_id="user-a")
        right = EventLog(map_id="int-map2", channel="private", type="y", payload={"ok": True},
                         recipient_user_id="user-b")
        for row in (wrong, right):
            for sub in dispatcher._subscribers.get("int-map2", []):
                if sub.wants(row):
                    sub.queue.put_nowait(row)

    emitter = asyncio.create_task(_emit_wrong_then_right_recipient())
    try:
        chunk = await asyncio.wait_for(agen.__anext__(), timeout=1)
        # user-b가 받은 첫 청크가 user-a용("x")이 아니라 user-b용("y")이어야 한다 — 새지 않았다는 증거.
        assert "\"type\": \"y\"" in chunk
        assert "\"type\": \"x\"" not in chunk
    finally:
        await emitter
        await agen.aclose()
