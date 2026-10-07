"""구독을 끊는 경우(#369, docs/events.md) — map.deleted 뒤 그 지도의 모든 구독, member.left 뒤 나간 사람의
그 지도 구독만 닫는다. 이벤트가 먼저 전달되고 그다음 끊긴다.

라우터의 SSE 제너레이터를 직접 돌리고, dispatcher._deliver로 행을 흘린다(_tick의 DB 조회 다음 단계).
Last-Event-ID 없이 구독하므로 DB는 필요 없다.
"""

import asyncio
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient

import main
from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from realtime.dispatcher import dispatcher
from realtime.router import private_events, public_events

MAP = "close-map"
OTHER_MAP = "close-other-map"


@dataclass(frozen=True)
class Row:
    seq: int
    map_id: str
    channel: str
    type: str
    payload: dict = field(default_factory=dict)
    recipient_user_id: str | None = None


class _AliveRequest:
    async def is_disconnected(self) -> bool:
        return False   # 클라이언트는 계속 붙어 있다 — 서버가 닫아야만 끝난다


async def _open(endpoint, map_id: str, user_id: str):
    response = await endpoint(
        request=_AliveRequest(), mapId=map_id, user=CurrentUser(user_id=user_id), last_event_id=None
    )
    agen = response.body_iterator
    # 제너레이터는 첫 __anext__에서야 구독한다 — 큐 대기에 들어갈 때까지 돌려 둔다.
    pending = asyncio.ensure_future(agen.__anext__())
    await asyncio.sleep(0)
    return agen, pending


async def _next_chunk(pending) -> str:
    return await asyncio.wait_for(pending, timeout=1)


async def _assert_ended(agen, pending=None):
    with pytest.raises(StopAsyncIteration):
        if pending is not None:
            await asyncio.wait_for(pending, timeout=1)
        else:
            await asyncio.wait_for(agen.__anext__(), timeout=1)


async def _close(agen, pending):
    pending.cancel()
    try:
        await pending
    except (asyncio.CancelledError, StopAsyncIteration):
        pass
    await agen.aclose()


@pytest.fixture(autouse=True)
def _no_leftover_subscriptions():
    yield
    assert dispatcher._subscribers.get(MAP) is None
    assert dispatcher._subscribers.get(OTHER_MAP) is None


@pytest.mark.asyncio
async def test_map_deleted_is_delivered_then_every_subscription_on_that_map_ends():
    a_pub, a_pub_p = await _open(public_events, MAP, "user-a")
    a_priv, a_priv_p = await _open(private_events, MAP, "user-a")
    b_pub, b_pub_p = await _open(public_events, MAP, "user-b")
    other, other_p = await _open(public_events, OTHER_MAP, "user-a")

    dispatcher._deliver([Row(1, MAP, "public", "map.deleted", {"map_id": MAP})])

    for agen, pending in ((a_pub, a_pub_p), (b_pub, b_pub_p)):
        assert "event: map.deleted\n" in await _next_chunk(pending)
        await _assert_ended(agen)
    await _assert_ended(a_priv, a_priv_p)   # 개인 채널은 전체 채널 이벤트를 받지 않고 끝나기만 한다

    assert not other_p.done(), "다른 지도의 구독은 그대로다"
    await _close(other, other_p)


@pytest.mark.parametrize("new_owner", [None, "user-b"], ids=["leave", "withdraw_transfer"])
@pytest.mark.asyncio
async def test_member_left_ends_only_the_leavers_subscriptions(new_owner):
    """나가기(new_owner_user_id=null)와 방장 탈퇴 위임(new_owner_user_id=후임)이 같다."""
    a_pub, a_pub_p = await _open(public_events, MAP, "user-a")
    a_priv, a_priv_p = await _open(private_events, MAP, "user-a")
    a_other, a_other_p = await _open(public_events, OTHER_MAP, "user-a")
    b_pub, b_pub_p = await _open(public_events, MAP, "user-b")
    b_priv, b_priv_p = await _open(private_events, MAP, "user-b")

    left = {"map_id": MAP, "user_id": "user-a", "new_owner_user_id": new_owner}
    dispatcher._deliver([Row(1, MAP, "public", "member.left", left)])

    assert "event: member.left\n" in await _next_chunk(a_pub_p)
    await _assert_ended(a_pub)
    await _assert_ended(a_priv, a_priv_p)

    assert "event: member.left\n" in await _next_chunk(b_pub_p)
    assert not a_other_p.done(), "나간 사람의 다른 지도 구독은 그대로다"
    assert not b_priv_p.done()

    # 남은 구성원은 계속 받는다
    b_pub_p = asyncio.ensure_future(b_pub.__anext__())
    dispatcher._deliver([
        Row(2, MAP, "public", "pin.created", {"id": "p1"}),
        Row(3, MAP, "private", "run.candidates_ready", {}, recipient_user_id="user-b"),
    ])
    assert "event: pin.created\n" in await _next_chunk(b_pub_p)
    assert "event: run.candidates_ready\n" in await _next_chunk(b_priv_p)

    await _close(a_other, a_other_p)
    await b_pub.aclose()
    await b_priv.aclose()


@pytest.mark.asyncio
async def test_rows_after_member_left_in_the_same_tick_do_not_reach_the_leaver():
    a_pub, a_pub_p = await _open(public_events, MAP, "user-a")
    b_pub, b_pub_p = await _open(public_events, MAP, "user-b")

    dispatcher._deliver([
        Row(1, MAP, "public", "member.left", {"map_id": MAP, "user_id": "user-a", "new_owner_user_id": None}),
        Row(2, MAP, "public", "pin.created", {"id": "p1"}),
    ])

    assert "event: member.left\n" in await _next_chunk(a_pub_p)
    await _assert_ended(a_pub)
    assert "event: member.left\n" in await _next_chunk(b_pub_p)
    assert "event: pin.created\n" in await asyncio.wait_for(b_pub.__anext__(), timeout=1)
    await b_pub.aclose()


@pytest.mark.asyncio
async def test_member_left_without_user_id_closes_nothing():
    """user_id가 빠진 행으로 지도 전체를 끊지 않는다."""
    b_pub, b_pub_p = await _open(public_events, MAP, "user-b")
    dispatcher._deliver([Row(1, MAP, "public", "member.left", {"map_id": MAP})])
    assert "event: member.left\n" in await _next_chunk(b_pub_p)
    b_pub_p = asyncio.ensure_future(b_pub.__anext__())
    await asyncio.sleep(0.05)
    assert not b_pub_p.done()
    await _close(b_pub, b_pub_p)


# ── 닫힌 뒤 재구독은 구독 시작 검사(require_map_member)에서 404 ──

@pytest.fixture()
def gate():
    """구성원 여부만 가짜로 — 나간 사람(user-a)은 역할 없음, 남은 구성원(user-b)은 member."""
    state = {"user": "user-a"}
    membership = FakeMembership({(MAP, "user-b"): "member"})
    main.app.dependency_overrides[get_membership_gateway] = lambda: membership
    main.app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id=state["user"])
    yield state
    main.app.dependency_overrides.pop(get_membership_gateway, None)
    main.app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.parametrize("path", [f"/maps/{MAP}/events", f"/maps/{MAP}/events/me"])
def test_resubscribe_after_leaving_is_404(gate, path):
    client = TestClient(main.app)   # with 없이 — lifespan(디스패처)을 띄우지 않는다
    r = client.get(path, headers={"Last-Event-ID": "0"})
    assert r.status_code == 404
