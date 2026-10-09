"""삭제한 지 오래된 지도 정리(#431, docs/architecture.md 1.4절) — 되돌릴 수 없는 작업이라 "무엇을 지우지 않는가"를
지우는 것만큼 꼼꼼히 본다. 지도 4개(오래전 삭제 / 정확히 30일 전 삭제 / 최근 삭제 / 살아 있음)를 같은 두 사용자가
실제 API로 만들고, 12개 테이블 전부에 행이 있는 상태에서 정리 명령을 돌린다."""

import contextlib
import io
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from auth.models import User
from auth.testing import session_cookie
from common.events import EventLog
from maps import purge
from maps.models import Invite, Map, Membership
from pins.models import Pin, Reaction
from places.models import Place, PlaceFact
from recommend.models import Candidate, EvidenceLine, Exclusion, RecommendRun, Region
from shortlist.models import Route, ShortlistItem

REGION = {"label": "부산", "lat": 35.1796, "lng": 129.0756}
NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)

# 정리가 지우는 테이블 13개(지도 행 포함). 이슈 #431의 "12개"는 maps를 뺀 지도 딸린 데이터까지 합친 표기다.
TABLE_NAMES = [
    "shortlist_items", "routes", "evidence_lines", "candidates", "regions", "exclusions", "recommend_runs",
    "reactions", "pins", "event_log", "invites", "memberships", "maps",
]


class _KeepOpen:
    """main()이 끝에 session.close()를 부른다 — 테스트 트랜잭션을 지키려고 close만 무시한다."""

    def __init__(self, session):
        self._session = session

    def __getattr__(self, name):
        return getattr(self._session, name)

    def close(self):
        pass


@pytest.fixture()
def clients(app_client, two_users):
    a = TestClient(app_client.app, cookies=session_cookie("user_a"))
    b = TestClient(app_client.app, cookies=session_cookie("user_b"))
    yield a, b
    a.close()
    b.close()


def _rows_by_map(db, map_id: str) -> dict[str, int]:
    """한 지도에 딸린 테이블의 행 수. 자식 테이블은 핀·run을 거쳐 센다."""
    pin_ids = select(Pin.id).where(Pin.map_id == map_id)
    run_ids = select(RecommendRun.id).where(RecommendRun.map_id == map_id)

    def count(model, *where):
        return db.execute(select(func.count()).select_from(model).where(*where)).scalar_one()

    return {
        "shortlist_items": count(ShortlistItem, ShortlistItem.map_id == map_id),
        "routes": count(Route, Route.map_id == map_id),
        "evidence_lines": count(EvidenceLine, EvidenceLine.run_id.in_(run_ids)),
        "candidates": count(Candidate, Candidate.run_id.in_(run_ids)),
        "regions": count(Region, Region.run_id.in_(run_ids)),
        "exclusions": count(Exclusion, Exclusion.map_id == map_id),
        "recommend_runs": count(RecommendRun, RecommendRun.map_id == map_id),
        "reactions": count(Reaction, Reaction.pin_id.in_(pin_ids)),
        "pins": count(Pin, Pin.map_id == map_id),
        "event_log": count(EventLog, EventLog.map_id == map_id),
        "invites": count(Invite, Invite.map_id == map_id),
        "memberships": count(Membership, Membership.map_id == map_id),
        "maps": count(Map, Map.id == map_id),
    }


def _shared_rows(db) -> dict[str, int]:
    """지도에 속하지 않아 정리가 절대 건드리면 안 되는 테이블."""
    return {
        "places": db.execute(select(func.count()).select_from(Place)).scalar_one(),
        "place_facts": db.execute(select(func.count()).select_from(PlaceFact)).scalar_one(),
        "users": db.execute(select(func.count()).select_from(User)).scalar_one(),
    }


def _build_map(a, b, db, pin_body, title: str) -> str:
    """방장 a·구성원 b, 핀 둘(+반응·확정), 동선, 추천 기록, 초대까지 정리 대상 테이블 전부에 행이 있는 지도."""
    map_id = a.post("/maps", json={"title": title, "start_date": "2026-11-01", "end_date": "2026-11-03",
                                   "region": REGION}).json()["id"]
    token = a.post(f"/maps/{map_id}/invite").json()["token"]
    assert b.post(f"/invites/{token}/accept").status_code == 200

    pin_ids = []
    for client, key in zip((a, b), ("seongsu-kalguksu", "hongdae-ramen")):
        r = client.post(f"/maps/{map_id}/pins", json=pin_body(key))
        assert r.status_code == 201, r.text
        pin_ids.append(r.json()["id"])
    for client in (a, b):
        for pin_id in pin_ids:
            assert client.put(f"/pins/{pin_id}/reaction", json={"type": "like"}).status_code == 200
    assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": pin_ids[0]}).status_code in (200, 201)
    db.add(Route(map_id=map_id, region_label="부산", ordered_pin_ids=pin_ids, total_distance_m=100, legs=[]))

    run = RecommendRun(id=uuid.uuid4(), map_id=map_id, category="음식점", requested_by="user_a", status="done")
    db.add(run)
    db.flush()
    region = Region(run_id=run.id, signature=title, label="부산", center_lat=35.18, center_lng=129.07, radius_m=1000)
    db.add(region)
    db.flush()
    db.add(Candidate(run_id=run.id, place_id=f"cand_{title}", region_id=region.id, lat=35.18, lng=129.07, rank=1))
    db.add(EvidenceLine(run_id=run.id, author_id="user_a", source="manual", text="t", badge="preferred"))
    db.add(Exclusion(map_id=map_id, category="음식점", place_id=f"ex_{title}", reason="dismissed",
                     run_id=run.id, requested_by="user_a"))
    db.commit()

    rows = _rows_by_map(db, map_id)
    assert all(count >= 1 for count in rows.values()), f"{title}: 비어 있는 테이블이 있다 {rows}"
    return map_id


def _delete(a, db, map_id: str, *, days_ago: int) -> None:
    """실제 삭제 API로 deleted_at을 찍고, 경과일만큼 과거로 돌린다."""
    assert a.delete(f"/maps/{map_id}").status_code == 204
    db.execute(update(Map).where(Map.id == map_id).values(deleted_at=NOW - timedelta(days=days_ago)))
    db.commit()


@pytest.fixture()
def world(clients, db_session, pin_body):
    a, b = clients
    ids = {name: _build_map(a, b, db_session, pin_body, name) for name in ("old", "edge", "recent", "live")}
    _delete(a, db_session, ids["old"], days_ago=40)
    _delete(a, db_session, ids["edge"], days_ago=30)  # 정확히 30일 — 기간이 찬 것으로 본다
    _delete(a, db_session, ids["recent"], days_ago=10)
    return ids


def _snapshot(db, ids: dict[str, str], names) -> dict[str, dict[str, int]]:
    return {name: _rows_by_map(db, ids[name]) for name in names}


def _run(db, *args: str) -> str:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        assert purge.main(list(args), session_factory=lambda: _KeepOpen(db), now=NOW) == 0
    return out.getvalue()


def test_purge_removes_every_table_of_expired_maps_and_keeps_everything_else(world, db_session):
    untouched = _snapshot(db_session, world, ["recent", "live"])
    shared = _shared_rows(db_session)
    expired_before = _snapshot(db_session, world, ["old", "edge"])

    output = _run(db_session, "--older-than-days", "30")

    for name in ("old", "edge"):
        assert set(_rows_by_map(db_session, world[name]).values()) == {0}, f"{name}가 덜 지워졌다"
    assert _snapshot(db_session, world, ["recent", "live"]) == untouched  # 기간 안 된 지도·삭제 안 된 지도
    assert _shared_rows(db_session) == shared                              # places·place_facts·users
    assert "지운 지도 2개" in output
    for table in TABLE_NAMES:
        total = sum(expired_before[name][table] for name in expired_before)
        assert f"{table}: {total}\n" in output


def test_dry_run_reports_counts_and_deletes_nothing(world, db_session):
    everything = _snapshot(db_session, world, world)
    shared = _shared_rows(db_session)

    dry = _run(db_session, "--older-than-days", "30", "--dry-run")

    assert _snapshot(db_session, world, world) == everything
    assert _shared_rows(db_session) == shared
    assert dry.startswith("[dry-run] 지울 지도 2개")
    # 같은 형식·같은 숫자: 실제 실행의 보고와 머리말·꼬리말만 다르다
    real = _run(db_session, "--older-than-days", "30")
    assert real.splitlines()[1:] == dry.splitlines()[1:-1]


def test_period_decides_which_maps_are_targets(world, db_session):
    assert _run(db_session, "--older-than-days", "60", "--dry-run").startswith("[dry-run] 지울 지도 0개")
    assert _run(db_session, "--older-than-days", "5", "--dry-run").startswith("[dry-run] 지울 지도 3개")
    assert _run(db_session, "--dry-run").startswith("[dry-run] 지울 지도 2개")  # 기본 30일


def test_purging_twice_is_harmless(world, db_session):
    _run(db_session, "--older-than-days", "30")
    again = _run(db_session, "--older-than-days", "30")

    assert again.startswith("지운 지도 0개")
    assert "합계: 0행" in again


def test_other_maps_of_the_same_users_survive_with_their_members_and_pins(world, db_session, clients):
    a, _ = clients
    _run(db_session, "--older-than-days", "30")

    assert {m["id"] for m in a.get("/maps").json()} == {world["live"]}
    assert a.get(f"/maps/{world['live']}/pins").status_code == 200
    assert len(a.get(f"/maps/{world['live']}/members").json()) == 2
    assert db_session.get(User, "user_a") is not None


def test_failure_in_the_middle_rolls_everything_back(world, db_session, monkeypatch):
    before = _snapshot(db_session, world, world)

    def boom(db, *, map_ids):
        raise RuntimeError("중간에 실패")

    monkeypatch.setattr(purge, "PURGE_STEPS", purge.PURGE_STEPS[:-1] + (boom,))  # maps 차례에서 실패
    with pytest.raises(RuntimeError):
        _run(db_session, "--older-than-days", "30")

    assert _snapshot(db_session, world, world) == before


def test_zero_days_is_rejected(world, db_session):
    with pytest.raises(SystemExit):
        _run(db_session, "--older-than-days", "0")
