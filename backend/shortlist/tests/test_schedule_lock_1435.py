"""#1435 — 일정 GET/PUT의 잠금 대기와 쿼리 수. 실제 PostgreSQL, 요청마다 따로 연결(스레드)."""

import threading
import time
import uuid
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from authz.core import Principal
from common.errors import AppError
from maps import api as maps_api
from maps.models import Map as MapRow
from pins.models import Pin as PinRow
from shortlist import flows, service
from shortlist.models import ShortlistItem
from shortlist.schemas import ScheduleUpdate

@pytest.fixture
def committed_map(test_engine):
    maker = sessionmaker(bind=test_engine)
    map_id = f"m_{uuid.uuid4().hex[:8]}"
    with maker() as s:
        s.add(MapRow(id=map_id, title="t", start_date=date(2026, 11, 10), end_date=date(2026, 11, 12), created_by="user_1"))
        s.flush()
        for i in range(4):
            pin = PinRow(map_id=map_id, category="음식점", kind="확정", origin="direct", source="live",
                         kakao_place_id=f"k_{map_id}_{i}", search_query="맛집", visibility="public", created_by="user_1")
            s.add(pin)
            s.flush()
            s.add(ShortlistItem(map_id=map_id, pin_id=pin.id, added_by="user_1", visit_order=i))
        s.commit()
    yield map_id, maker
    with maker() as s:
        s.execute(text("DELETE FROM shortlist_items WHERE map_id=:m"), {"m": map_id})
        s.execute(text("DELETE FROM event_log WHERE map_id=:m"), {"m": map_id})
        s.execute(text("DELETE FROM pins WHERE map_id=:m"), {"m": map_id})
        s.execute(text("DELETE FROM maps WHERE id=:m"), {"m": map_id})
        s.commit()


def _principal(map_id):
    return Principal("user_1", map_id, "member")


def _hold_write_locks(maker, map_id, seconds, started):
    """저장(PUT)이 쥐는 잠금 — 지도 행 FOR UPDATE + 확정 리스트 advisory lock — 을 seconds 동안 쥔다."""
    with maker() as s:
        assert maps_api.lock_map_if_alive(s, map_id)
        service.lock_shortlist(s, map_id)
        started.set()
        time.sleep(seconds)
        s.commit()


def _timed(maker, map_id, **kwargs):
    with maker() as s:
        start = time.perf_counter()
        result = flows.schedule(s, map_id=map_id, principal=_principal(map_id), **kwargs)
        s.commit()
        return time.perf_counter() - start, result


def test_get_does_not_wait_for_the_save_lock(committed_map):
    map_id, maker = committed_map
    started = threading.Event()
    holder = threading.Thread(target=_hold_write_locks, args=(maker, map_id, 1.0, started))
    holder.start()
    started.wait()

    elapsed, result = _timed(maker, map_id)
    holder.join()

    assert elapsed < 0.5   # 수정 전에는 잠금을 쥔 저장이 끝나는 1초 뒤에야 끝났다
    assert len(result.items) == 4


def test_save_still_waits_for_the_lock_holder(committed_map):
    # 쓰기 직렬화는 그대로다 — 같은 지도의 확정 리스트 변경과 저장은 줄을 선다
    map_id, maker = committed_map
    with maker() as s:
        _, current = _timed(maker, map_id)
    update = ScheduleUpdate(version=current.version, groups=[{"date": None, "item_ids": [str(i.id) for i in current.items]}])
    started = threading.Event()
    holder = threading.Thread(target=_hold_write_locks, args=(maker, map_id, 1.0, started))
    holder.start()
    started.wait()

    elapsed, _ = _timed(maker, map_id, update=update)
    holder.join()

    assert elapsed >= 0.9


def test_get_skips_an_item_whose_pin_was_deleted_meanwhile(committed_map):
    map_id, maker = committed_map
    with maker() as s:
        s.execute(text("UPDATE pins SET deleted_at = now() WHERE id = (SELECT pin_id FROM shortlist_items WHERE map_id=:m LIMIT 1)"),
                  {"m": map_id})
        s.commit()

    _, result = _timed(maker, map_id)

    assert len(result.items) == 3   # 통째로 404가 되지 않는다


def test_get_of_deleted_map_is_404(committed_map):
    map_id, maker = committed_map
    with maker() as s:
        s.execute(text("UPDATE maps SET deleted_at = now() WHERE id=:m"), {"m": map_id})
        s.commit()

    with pytest.raises(AppError):
        _timed(maker, map_id)
