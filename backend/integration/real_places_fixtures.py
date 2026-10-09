"""실제 장소 DB(PostGIS) 위에서 HTTP로 도는 통합 테스트용 공용 픽스처 — 성수 일대 가상 장소 6곳(라벨 포함), 실제 places
게이트웨이, ② 대역(방향을 내는 구현), 지도·구성원 둘. `app_client`와 달리 FakePlaces를 끼우지 않는다."""

import uuid  # noqa: F401
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from auth.testing import session_cookie
from common.events import EventLog
from common.database import get_db_session, session_scope
from main import app
from places import repository
from places.ingest import LabelRow, PlaceRow
from places.models import Place
from recommend.deps import (
    RealPlaceFactsGateway, RealPlaceSearchGateway, get_place_facts_gateway, get_place_search_gateway,
)

REGION = {"label": "성수", "lat": 37.5445, "lng": 127.0561}
NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)

# (source_id, 이름, 위도, 경도, {fact_key: value}) — 전부 성수 중심 700m 안
PLACES = {
    "K": ("성수 한식집", 37.5447, 127.0563, {"cuisine_korean": True, "cuisine_raw_fish": False, "spicy_focused": False}),
    "R": ("성수 횟집", 37.5449, 127.0558, {"cuisine_korean": False, "cuisine_raw_fish": True, "spicy_focused": False}),
    "B": ("성수 분식집", 37.5441, 127.0566, {"cuisine_korean": False, "cuisine_raw_fish": False, "spicy_focused": False}),
    "S": ("성수 매운집", 37.5443, 127.0554, {"cuisine_korean": False, "cuisine_raw_fish": False, "spicy_focused": True}),
    "C": ("성수 조개구이", 37.5451, 127.0569, {"cuisine_korean": False, "cuisine_raw_fish": False, "spicy_focused": False}),
    "U": ("성수 이름모를집", 37.5439, 127.0560, {}),
}


@pytest.fixture()
def own_db(db_session):
    repository.upsert_places(db_session, [
        PlaceRow("permit", sid, name, "음식점", f"서울 성동구 {sid}", None, lat, lng, "open")
        for sid, (name, lat, lng, _) in PLACES.items()
    ])
    repository.upsert_facts(db_session, [
        LabelRow("permit", sid, key, value, "known", 3, NOW)
        for sid, (_, _, _, facts) in PLACES.items() for key, value in facts.items()
    ])
    db_session.flush()
    return db_session


@pytest.fixture()
def place_ids(own_db):
    rows = {p.source_id: p for p in own_db.execute(select(Place)).scalars()}
    return {sid: str(rows[sid].id) for sid in PLACES}


@pytest.fixture()
def real_client(db_session, own_db, monkeypatch):
    """app_client와 달리 FakePlaces를 끼우지 않는다 — 핀 매칭·후보 풀·라벨이 모두 실제 places 구현이다."""
    from fastapi.testclient import TestClient

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    app.dependency_overrides[get_place_search_gateway] = lambda: RealPlaceSearchGateway(db=db_session)
    app.dependency_overrides[get_place_facts_gateway] = lambda: RealPlaceFactsGateway(db=db_session)
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


def plan_with(monkeypatch, planner):
    """② 대역을 recommend의 EvidencePlanGateway 자리에 끼운다(#219) — 대역은 입력 글마다 줄 묶음을 돌려주는 함수다.
    llm.api.plan_evidence를 거치므로 검증·실패 변환(PlanEvidenceFailed)은 실제와 같다. 테스트가 끝나면 원복된다."""
    from llm import api as llm_api
    from recommend.deps import get_evidence_plan_gateway

    class _Gateway:
        def plan_evidence(self, raw_reasons):
            return llm_api.plan_evidence(raw_reasons, planner=planner)

    monkeypatch.setitem(app.dependency_overrides, get_evidence_plan_gateway, lambda: _Gateway())


@pytest.fixture()
def fake_planner(monkeypatch):
    """② 대역 — 사유 문구로 fact_key·wants를 낸다(진짜 Luna 대신). 방향을 모르는 말은 null."""
    from llm.schemas import EvidenceLine

    mapping = {
        "한식 말고": ("cuisine_korean", False),
        "회 좋아해": ("cuisine_raw_fish", True),
        "너무 매워요": ("spicy_focused", False),    # 취향 키(#378) — "피하겠다"는 방향
    }

    def planner(raw_reasons):
        out = []
        for reason in raw_reasons:
            key, wants = next((v for k, v in mapping.items() if k in reason["text"]), (None, None))
            out.append([EvidenceLine(**{**reason, "fact_key": key, "wants": wants if key else None})])
        return out

    plan_with(monkeypatch, planner)
    return planner


@pytest.fixture()
def members(real_client, two_users):
    from fastapi.testclient import TestClient

    a = TestClient(real_client.app, cookies=session_cookie("user_a"))
    b = TestClient(real_client.app, cookies=session_cookie("user_b"))
    r = a.post("/maps", json={"title": "성수", "start_date": "2026-11-01", "end_date": "2026-11-02", "region": REGION})
    assert r.status_code == 201, r.text
    map_id = r.json()["id"]
    inv = a.post(f"/maps/{map_id}/invite").json()
    assert b.post(f"/invites/{inv['token']}/accept").status_code == 200
    yield a, b, map_id
    a.close()
    b.close()


def _pin(client, map_id, sid, place_ids):
    name, lat, lng, _ = PLACES[sid]
    r = client.post(f"/maps/{map_id}/pins", json={
        "category": "음식점", "source": "search", "place_id": f"kakao:{sid}", "place_name": name, "lat": lat, "lng": lng})
    assert r.status_code == 201, r.text
    assert r.json()["place_name"] == name
    return r.json()["id"]


def _pin(client, map_id, sid, place_ids):
    name, lat, lng, _ = PLACES[sid]
    r = client.post(f"/maps/{map_id}/pins", json={
        "category": "음식점", "source": "search", "place_id": f"kakao:{sid}", "place_name": name, "lat": lat, "lng": lng})
    assert r.status_code == 201, r.text
    assert r.json()["place_name"] == name
    return r.json()["id"]


def _events(db_session, map_id, type_):
    return list(db_session.execute(
        select(EventLog).where(EventLog.map_id == map_id, EventLog.type == type_).order_by(EventLog.seq)
    ).scalars())


def _recommend(a, b, map_id, place_ids, *, executed=True):
    """K·S에 핀을 찍고 사유를 남긴 뒤 run을 만들고(선택적으로 실행) (run_id, candidates)를 돌려준다."""
    k = _pin(a, map_id, "K", place_ids)
    s = _pin(a, map_id, "S", place_ids)
    assert a.put(f"/pins/{k}/reaction", json={"type": "against", "reason_text": "한식 말고 다른 거"}).status_code == 200
    assert b.put(f"/pins/{s}/reaction", json={"type": "against", "reason_text": "너무 매워요"}).status_code == 200
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    candidates = []
    if executed:
        assert a.post(f"/runs/{run_id}/execute").status_code == 202
        candidates = a.get(f"/runs/{run_id}/result").json()["candidates"]
    return run_id, candidates
