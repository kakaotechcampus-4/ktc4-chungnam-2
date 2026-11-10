"""realtime 시험 공용 도우미."""

PRESENCE_PREFIX = "event: member.presence"


async def skip_presence(agen):
    """SSE 제너레이터에서 member.presence 청크만 걸러 낸다 — 이 시험들이 보는 것(전달·종료·ping·재전송)을
    접속 알림(test_presence.py가 본다)이 가로채지 않게 한다. 닫기·취소는 안쪽 제너레이터로 그대로 전해진다."""
    try:
        async for chunk in agen:
            if not chunk.startswith(PRESENCE_PREFIX):
                yield chunk
    finally:
        await agen.aclose()


def drain_presence(*subs) -> None:
    """구독 큐에 쌓인 member.presence만 비운다(다른 행이 있으면 그대로 둔다)."""
    for sub in subs:
        kept = []
        while not sub.queue.empty():
            item = sub.queue.get_nowait()
            if getattr(item, "type", None) != "member.presence":
                kept.append(item)
        for item in kept:
            sub.queue.put_nowait(item)
