"""관찰 루프 테스트용 — 실제로 커밋하는 지도 픽스처(test_flows.py).

observe_map과 run_tick은 자기 세션을 열고 커밋한다(12.6). 그래서 conftest의 롤백 세션(db_session)이 아니라 테스트
DB에 붙는 sessionmaker를 넘기고, 끝나면 이 테스트가 만든 지도와 사용자의 행만 지운다(다른 모듈 테스트와 같은 DB를
쓰므로 테이블을 통째로 비우지 않는다). 사용자 id는 테스트마다 접두어를 붙여 다른 테스트의 u1과 겹치지 않게 한다.

`latest_seq_by_map`의 보존 기간(24시간)은 실제 시계로 잘라서, 관찰 시각(now)과 이벤트 시각도 실제 시계 근처로 둔다.
"""

import uuid
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from agent import api as agent_api
from agent import core
from auth.models import User
from auth.testing import ensure_users
from common.events import EventLog
from maps.models import Map, Membership
from pins.models import Pin, Reaction
from places.schemas import PlaceInfo
from shortlist.models import ShortlistItem


class World:
    def __init__(self, factory, now: datetime):
        self.factory = factory
        self.now = now
        self.today: date = core.kst_date(now)
        self.prefix = f"agt{uuid.uuid4().hex[:6]}"
        self.map_ids: list[str] = []
        self.user_ids: set[str] = set()

    def uid(self, name: str) -> str:
        return f"{self.prefix}_{name}"

    # ------------------------------------------------------------ 만들기 (각각 커밋한다)

    def map(self, *, members=("u1", "u2", "u3"), start: date | None = None, end: date | None = None,
            deleted: bool = False) -> str:
        start = start or self.today + timedelta(days=30)
        end = end or start + timedelta(days=2)
        uids = [self.uid(m) for m in members]
        with self.factory() as db:
            ensure_users(db, *uids)
            row = Map(title="지도", start_date=start, end_date=end, created_by=uids[0],
                      deleted_at=self.now - timedelta(hours=1) if deleted else None)
            db.add(row)
            db.flush()
            for i, u in enumerate(uids):
                db.add(Membership(map_id=row.id, user_id=u, role="owner" if i == 0 else "member",
                                  joined_at=self.now - timedelta(days=10, minutes=-i)))
            db.commit()
            self.map_ids.append(row.id)
            self.user_ids.update(uids)
            return row.id

    def pin(self, map_id: str, *, category: str = "음식점", by: str = "u1", hours_ago: float = 100,
            place_id: str | None = None) -> str:
        with self.factory() as db:
            row = Pin(
                id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct",
                place_id=place_id or f"place_{uuid.uuid4().hex[:8]}",
                geom=func.ST_SetSRID(func.ST_MakePoint(127.0, 37.5), 4326),
                visibility="public", created_by=self.uid(by), created_at=self.now - timedelta(hours=hours_ago),
            )
            db.add(row)
            db.commit()
            return str(row.id)

    def live_pin(self, map_id: str, query: str, *, category: str = "음식점", by: str = "u1",
                 hours_ago: float = 100) -> str:
        """실시간 핀(#382) — 자체 DB 장소가 없고 사용자가 친 검색어만 있다."""
        with self.factory() as db:
            row = Pin(
                id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct", source="live",
                kakao_place_id=f"kakao:{uuid.uuid4().hex[:8]}", search_query=query, visibility="public",
                created_by=self.uid(by), created_at=self.now - timedelta(hours=hours_ago),
            )
            db.add(row)
            db.commit()
            return str(row.id)

    def delete_pin(self, pin_id: str) -> None:
        with self.factory() as db:
            db.get(Pin, uuid.UUID(pin_id)).deleted_at = self.now
            db.commit()

    def react(self, pin_id: str, user: str, type_: str, *, hours_ago: float, text: str | None = None) -> str:
        with self.factory() as db:
            row = Reaction(id=uuid.uuid4(), pin_id=uuid.UUID(pin_id), user_id=self.uid(user), type=type_,
                           reason_text=text, updated_at=self.now - timedelta(hours=hours_ago))
            db.add(row)
            db.commit()
            return str(row.id)

    def confirm(self, map_id: str, pin_id: str, *, by: str = "u1", hours_ago: float = 50) -> None:
        with self.factory() as db:
            db.add(ShortlistItem(map_id=map_id, pin_id=uuid.UUID(pin_id), added_by=self.uid(by),
                                 added_at=self.now - timedelta(hours=hours_ago)))
            db.commit()

    def event(self, map_id: str, *, seconds_ago: float = 600) -> int:
        with self.factory() as db:
            row = EventLog(map_id=map_id, channel="public", type="pin.created", payload={},
                           created_at=self.now - timedelta(seconds=seconds_ago))
            db.add(row)
            db.commit()
            return row.seq

    def delete_map(self, map_id: str) -> None:
        with self.factory() as db:
            db.get(Map, map_id).deleted_at = self.now
            db.commit()

    def gap_map(self, **kw) -> str:
        """카테고리 공백이 둘(카페, 관광지) 있는 지도 — 음식점 확정 2곳. 반응이 없어 다른 신호는 없다."""
        map_id = self.map(**kw)
        for _ in range(2):
            self.confirm(map_id, self.pin(map_id, category="음식점"))
        return map_id

    def unseen_map(self, *pins: tuple[str, str], **kw) -> tuple[str, list[str]]:
        """반응 공백(6.4)만 있는 지도 — u1이 100시간 전에 찍은 핀에 아무도 반응하지 않았다. pins는 (종류, 값):
        ("db", place_id) 또는 ("live", 검색어). (map_id, 핀 id 목록)."""
        map_id = self.map(**kw)
        ids = [self.live_pin(map_id, value) if kind == "live" else self.pin(map_id, place_id=value)
               for kind, value in pins]
        return map_id, ids

    # ------------------------------------------------------------ 읽기

    def rows(self, model, **where):
        with self.factory() as db:
            stmt = select(model)
            for k, v in where.items():
                stmt = stmt.where(getattr(model, k) == v)
            return db.execute(stmt).scalars().all()

    def one(self, model, **where):
        rows = self.rows(model, **where)
        assert len(rows) == 1, rows
        return rows[0]

    def count_events(self) -> int:
        with self.factory() as db:
            return db.execute(
                select(func.count()).select_from(EventLog).where(EventLog.map_id.in_(self.map_ids))
            ).scalar_one()

    def agent_events(self, map_id: str) -> list[tuple[str, dict]]:
        """그 지도의 agent.* 이벤트 (type, payload), seq 순."""
        with self.factory() as db:
            return [(r.type, r.payload) for r in db.execute(
                select(EventLog).where(EventLog.map_id == map_id, EventLog.type.like("agent.%")).order_by(EventLog.seq)
            ).scalars().all()]

    # ------------------------------------------------------------ 정리

    def cleanup(self) -> None:
        if not self.map_ids:
            return
        ids = self.map_ids
        with self.factory() as db:
            agent_api.purge_map_data(db, map_ids=ids)
            db.execute(delete(ShortlistItem).where(ShortlistItem.map_id.in_(ids)))
            db.execute(delete(Reaction).where(Reaction.pin_id.in_(select(Pin.id).where(Pin.map_id.in_(ids)))))
            db.execute(delete(Pin).where(Pin.map_id.in_(ids)))
            db.execute(delete(Membership).where(Membership.map_id.in_(ids)))
            db.execute(delete(EventLog).where(EventLog.map_id.in_(ids)))
            db.execute(delete(Map).where(Map.id.in_(ids)))
            db.execute(delete(User).where(User.id.in_(self.user_ids)))
            db.commit()


def fake_places(names: dict[str, str]):
    """places.api.get_places 대역 — place_id → 장소 이름. 없는 id는 빠진다(진짜와 같다)."""
    def get_places(place_ids, *, db=None):
        return {pid: PlaceInfo(pid, names[pid], 37.5, 127.0, "음식점", None, None) for pid in place_ids if pid in names}
    return get_places


def real_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)
