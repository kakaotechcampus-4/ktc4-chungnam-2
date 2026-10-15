"""core.py 테스트용 스냅샷 만들기 — DB 없이 Snapshot을 직접 조립한다. 행동 목록은 snapshot.build와 같은
`derive_actions`로 만든다."""

from datetime import date, datetime, timedelta, timezone

from agent.snapshot import MapInfo, Member, Pin, Reaction, Reason, ShortlistItem, Snapshot, derive_actions

NOW = datetime(2026, 10, 15, 3, 0, tzinfo=timezone.utc)   # KST 12:00
TODAY = date(2026, 10, 15)
FAR_START = TODAY + timedelta(days=30)   # D-day 계수 1.0


def hours(n: float) -> timedelta:
    return timedelta(hours=n)


def member(user_id: str, *, joined_at: datetime = NOW - hours(240)) -> Member:
    return Member(user_id=user_id, alias="", joined_at=joined_at)


def pin(pin_id: str, *, category: str = "음식점", by: str = "u1", at: datetime = NOW - hours(100)) -> Pin:
    return Pin(pin_id=pin_id, category=category, source="db", place_id=f"place_{pin_id}", search_query=None,
               created_by=by, created_at=at)


def react(reaction_id: str, pin_id: str, user_id: str, type_: str, at: datetime) -> Reaction:
    return Reaction(reaction_id=reaction_id, pin_id=pin_id, user_id=user_id, type=type_, updated_at=at)


def reason(r: Reaction, text: str | None, *, category: str = "음식점", alias: str | None = None) -> Reason:
    """반응 r의 사유(글). 칩은 비운다."""
    return Reason(reaction_id=r.reaction_id, pin_id=r.pin_id, category=category, alias=alias, type=r.type, text=text,
                  chips=(), updated_at=r.updated_at, pin_deleted=False)


def item(pin_id: str, *, by: str = "u1", at: datetime = NOW - hours(50)) -> ShortlistItem:
    return ShortlistItem(pin_id=pin_id, added_by=by, added_at=at)


def snap(
    *, members=("u1", "u2", "u3"), pins=(), reactions=(), shortlist=(), last_run_at=None, reasons=(),
    start_date: date = FAR_START, end_date: date | None = None, today: date = TODAY,
) -> Snapshot:
    ms = tuple(
        m if isinstance(m, Member) else member(m) for m in members
    )
    ms = tuple(Member(user_id=m.user_id, alias=f"m{i}", joined_at=m.joined_at) for i, m in enumerate(ms, start=1))
    pins, reactions, shortlist = tuple(pins), tuple(reactions), tuple(shortlist)
    return Snapshot(
        map=MapInfo(map_id="map_1", start_date=start_date, end_date=end_date or start_date + timedelta(days=2),
                    deleted=False),
        today=today, members=ms, pins=pins, reactions=reactions, reasons=tuple(reasons), shortlist=shortlist,
        last_run_at=dict(last_run_at or {}), actions=derive_actions(pins, reactions, shortlist),
    )
