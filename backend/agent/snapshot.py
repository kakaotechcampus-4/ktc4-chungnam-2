"""관찰 한 번이 보는 지도 사본(docs/agent-v2.md 12.7). 다른 모듈의 `api.py`로만 읽는다(#113).

- 읽기 전용이고 커밋하지 않는다. 세션과 격리 수준(REPEATABLE READ)은 호출하는 쪽(#515 observe_map)이 정한다.
- **공개 데이터만 담는다**(명세 2절 2번). run은 카테고리별 마지막 생성 시각만 담고 `has_run_since`의 bool로만 쓴다.
  run의 후보, 근거 줄, 요청자, 제외 목록은 읽지도 담지도 않는다.
- 사유 글(`Reason.text`)은 공개 데이터라 사본에는 담지만(모델 입력과 검증용, M1), Signal과 agent 테이블에는 넣지
  않는다(명세 2절 13번).
- 구성원 별칭(m1, m2 …)을 여기서 매긴다. joined_at 순이다.
- `latest_seq`, `latest_event_at`은 `realtime.api.latest_seq_by_map`으로 같은 트랜잭션에서 채운다(12.5, #515).
  event_log 보존(24시간) 안에 이 지도 이벤트가 없으면 None이다. 커서 계산에만 쓰고 상태는 도메인 테이블에서 읽는다.

데이터 모양(dataclass)도 여기 둔다. core.py는 이 모양만 알고 DB는 모른다.
"""

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy.orm import Session

from agent import core
from common import categories
from maps import api as maps_api
from pins import api as pins_api
from realtime import api as realtime_api
from recommend import api as recommend_api
from shortlist import api as shortlist_api


@dataclass(frozen=True)
class MapInfo:
    map_id: str
    start_date: date
    end_date: date
    deleted: bool


@dataclass(frozen=True)
class Member:
    user_id: str
    alias: str            # m1, m2 … (명세 2절 11번 — 모델과 문구에는 이름 대신 이것만)
    joined_at: datetime


@dataclass(frozen=True)
class Pin:
    """삭제되지 않은 공개 핀. 이름은 담지 않는다 — db 핀은 place_id로, live 핀은 search_query로 렌더 때 정한다."""
    pin_id: str
    category: str
    source: str           # db | live (#382)
    place_id: str | None
    search_query: str | None
    created_by: str
    created_at: datetime


@dataclass(frozen=True)
class Reaction:
    """삭제되지 않은 핀의 반응. ♥(like)와 🚫(against)뿐이고 미확인은 행이 없다(#360)."""
    reaction_id: str
    pin_id: str
    user_id: str
    type: str
    updated_at: datetime


@dataclass(frozen=True)
class Chip:
    chip_id: str
    label: str
    fact_key: str | None
    wants: bool | None


@dataclass(frozen=True)
class Reason:
    """사유가 있는 반응(명세 8절). 삭제된 핀의 사유도 담는다(#243) — `pin_deleted`로 구분한다."""
    reaction_id: str
    pin_id: str
    category: str
    alias: str | None     # 지금 구성원이 아니면 None
    type: str
    text: str | None
    chips: tuple[Chip, ...]
    updated_at: datetime
    pin_deleted: bool


@dataclass(frozen=True)
class ShortlistItem:
    pin_id: str
    added_by: str
    added_at: datetime


@dataclass(frozen=True)
class Action:
    """행동 하나(명세 6절 첫 문단): 반응 등록과 수정, 핀 생성, 확정 추가. 삭제되지 않은 핀 기준, 지금 카테고리."""
    kind: str             # reaction | pin | shortlist
    user_id: str
    category: str
    at: datetime


@dataclass(frozen=True)
class Snapshot:
    map: MapInfo
    today: date           # KST 날짜
    members: tuple[Member, ...] = ()
    pins: tuple[Pin, ...] = ()
    reactions: tuple[Reaction, ...] = ()
    reasons: tuple[Reason, ...] = ()
    shortlist: tuple[ShortlistItem, ...] = ()
    last_run_at: dict[str, datetime] = field(default_factory=dict)   # 카테고리 → 마지막 run 시각. has_run_since로만
    actions: tuple[Action, ...] = ()
    latest_seq: int | None = None          # 이 지도의 가장 큰 event_log seq(12.5)
    latest_event_at: datetime | None = None   # 그 이벤트의 created_at

    def __post_init__(self):
        object.__setattr__(self, "_pins_by_id", {p.pin_id: p for p in self.pins})
        object.__setattr__(self, "_confirmed", frozenset(i.pin_id for i in self.shortlist))
        reacted = {(r.user_id, r.pin_id) for r in self.reactions}
        object.__setattr__(self, "_reacted", frozenset(reacted))

    @property
    def member_count(self) -> int:
        return len(self.members)

    @property
    def action_times(self) -> list[datetime]:
        return [a.at for a in self.actions]

    def pin(self, pin_id: str) -> Pin | None:
        return self._pins_by_id.get(pin_id)

    def reactions_of(self, pin_id: str) -> list[Reaction]:
        return [r for r in self.reactions if r.pin_id == pin_id]

    def is_confirmed(self, pin_id: str) -> bool:
        return pin_id in self._confirmed

    def has_reaction(self, user_id: str, pin_id: str) -> bool:
        return (user_id, pin_id) in self._reacted

    def has_run_since(self, category: str, t0: datetime) -> bool:
        """t0 뒤에 그 카테고리 run이 있었나. bool만 내보낸다 — 모델 입력과 문구에 넣지 않는다(명세 2절 2번)."""
        last = self.last_run_at.get(category)
        return last is not None and last > t0


def build(db: Session, map_id: str, now: datetime) -> Snapshot | None:
    """지도가 없으면(정리까지 끝난 지도) None. 삭제된 지도는 지도 정보만 담고 나머지는 비운다 — observe_map은
    `snap.map.deleted`를 보고 바로 끝낸다(12.4)."""
    found = maps_api.get_map_for_agent(db, map_id)
    if found is None:
        return None
    map_info = MapInfo(
        map_id=found["map_id"], start_date=found["start_date"], end_date=found["end_date"], deleted=found["deleted"],
    )
    today = core.kst_date(now)
    latest_seq, latest_event_at = realtime_api.latest_seq_by_map(db).get(map_id, (None, None))
    if map_info.deleted:
        return Snapshot(map=map_info, today=today, latest_seq=latest_seq, latest_event_at=latest_event_at)

    members = tuple(
        Member(user_id=m["user_id"], alias=f"m{i}", joined_at=m["joined_at"])
        for i, m in enumerate(found["members"], start=1)
    )
    alias_of = {m.user_id: m.alias for m in members}

    matrix = pins_api.list_reaction_matrix(db, map_id=map_id)
    pins = tuple(
        Pin(
            pin_id=p["pin_id"], category=p["category"], source=p["source"], place_id=p["place_id"],
            search_query=p["search_query"], created_by=p["created_by"], created_at=p["created_at"],
        )
        for p in matrix
    )
    reactions = tuple(
        Reaction(
            reaction_id=r["reaction_id"], pin_id=p["pin_id"], user_id=r["user_id"], type=r["type"],
            updated_at=r["updated_at"],
        )
        for p in matrix for r in p["reactions"]
    )
    alive = {p.pin_id: p for p in pins}

    reasons = tuple(
        Reason(
            reaction_id=r["reaction_id"], pin_id=r["pin_id"], category=category, alias=alias_of.get(r["user_id"]),
            type=r["type"], text=r["reason_text"], chips=tuple(Chip(**c) for c in r["chips"]),
            updated_at=r["updated_at"], pin_deleted=r["pin_id"] not in alive,
        )
        for category in categories.pinnable()
        for r in pins_api.list_reasoned_reactions(db, map_id=map_id, category=category)
    )

    # 확정한 핀을 지우면 확정 항목도 함께 빠진다(#235). 그래도 남은 옛 행은 "삭제되지 않은 핀 기준"(6절)으로 뺀다
    shortlist = tuple(
        ShortlistItem(pin_id=i["pin_id"], added_by=i["added_by"], added_at=i["added_at"])
        for i in shortlist_api.list_items_for_agent(db, map_id=map_id)
        if i["pin_id"] in alive
    )

    return Snapshot(
        map=map_info, today=today, members=members, pins=pins, reactions=reactions, reasons=reasons,
        shortlist=shortlist, last_run_at=recommend_api.last_run_at_by_category(db, map_id=map_id),
        actions=derive_actions(pins, reactions, shortlist), latest_seq=latest_seq, latest_event_at=latest_event_at,
    )


def derive_actions(
    pins: tuple[Pin, ...], reactions: tuple[Reaction, ...], shortlist: tuple[ShortlistItem, ...],
) -> tuple[Action, ...]:
    """행동 세 가지를 시각 순으로. 반응과 확정 항목은 삭제되지 않은 핀의 것만 받는다고 본다(카테고리는 지금 분류, #466)."""
    category_of = {p.pin_id: p.category for p in pins}
    return tuple(sorted(
        [Action("pin", p.created_by, p.category, p.created_at) for p in pins]
        + [Action("reaction", r.user_id, category_of[r.pin_id], r.updated_at) for r in reactions]
        + [Action("shortlist", i.added_by, category_of[i.pin_id], i.added_at) for i in shortlist],
        key=lambda a: a.at,
    ))
