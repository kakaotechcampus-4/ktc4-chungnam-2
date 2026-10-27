"""GET /places/nearest (#473) — 100m 안 자체 DB 장소를 가까운 순으로, pinnable만. 실제 PostgreSQL+PostGIS."""

import logging
import uuid

import pytest
from sqlalchemy import text

from auth.testing import session_cookie
from main import app  # noqa: F401
from places import api as places_api, logguard, repository
from places.models import Place
from places.ratelimit import SlidingWindowLimiter

LAT, LNG = 37.5445, 127.0561   # 위도 0.0009도 ≈ 100m


@pytest.fixture()
def client(app_client, two_users):
    from fastapi.testclient import TestClient

    c = TestClient(app_client.app, cookies=session_cookie("user_a"))
    yield c
    c.close()


@pytest.fixture(autouse=True)
def _fresh_limiter(monkeypatch):
    monkeypatch.setattr(places_api, "search_limiter", SlidingWindowLimiter(1000))


def _add(db, name, dlat=0.0, category="음식점", status="open", address=None, source="permit"):
    p = Place(source=source, source_id=uuid.uuid4().hex, name=name, category=category, address=address, status=status,
              geom=f"SRID=4326;POINT({LNG} {LAT + dlat})")
    db.add(p)
    db.flush()
    return str(p.id)


def _get(client, **params):
    return client.get("/places/nearest", params={"lat": LAT, "lng": LNG, **params})


def test_returns_own_db_places_within_100m_closest_first(client, db_session):
    far = _add(db_session, "먼 가게", 0.0007)
    near = _add(db_session, "가까운 가게", 0.0002, address="서울 성동구 성수동2가 1")
    _add(db_session, "반경 밖 가게", 0.0015)
    r = _get(client)
    assert r.status_code == 200
    assert [h["place_id"] for h in r.json()] == [f"own:{near}", f"own:{far}"]
    first = r.json()[0]
    assert first["pinnable"] is True and first["category"] == "음식점" and first["address"] == "서울 성동구 성수동2가 1"
    assert first["place_source"] == {"provider": "permit"}   # 카카오 값이 없다 — 자체 DB 출처
    assert set(first) <= {"place_id", "place_name", "lat", "lng", "category", "address", "place_source", "pinnable"}


def test_nothing_nearby_is_an_empty_array(client, db_session):
    _add(db_session, "먼 가게", 0.01)
    assert _get(client).json() == []


def test_category_filter_and_unsupported_category(client, db_session):
    _add(db_session, "성수 식당", 0.0001)
    _add(db_session, "성수 카페", 0.0002, category="카페", source="tourapi")
    assert [h["place_name"] for h in _get(client, category="카페").json()] == ["성수 카페"]
    assert _get(client, category="카페").json()[0]["place_source"]["provider"] == "tourapi"
    assert _get(client, category="숙소").json() == []   # 자체 DB에 없는 분류
    assert _get(client, category="없는분류").status_code == 422


def test_closed_places_are_left_out(client, db_session):
    _add(db_session, "폐업 가게", 0.0001, status="closed")
    assert _get(client).json() == []


def test_at_most_five(client, db_session):
    for i in range(8):
        _add(db_session, f"가게{chr(0xAC00 + i * 50)}", 0.0001 * (i + 1))
    assert len(_get(client).json()) == 5


def test_places_the_pin_flow_would_reject_are_not_returned(client, db_session):
    """같은 이름 두 점포가 같은 자리에 있으면 핀 생성 매칭이 모호해서 거절한다 — 미리 뺀다(pinnable=true만)."""
    _add(db_session, "쌍둥이 식당", 0.0)
    _add(db_session, "쌍둥이 식당", 0.0)
    ok = _add(db_session, "홀로 식당", 0.0004)
    assert [h["place_id"] for h in _get(client).json()] == [f"own:{ok}"]


@pytest.mark.parametrize("params", [{"lat": LAT}, {"lng": LNG}, {"lat": 91, "lng": LNG}, {"lat": LAT, "lng": 181}, {"lat": "x", "lng": LNG}])
def test_invalid_coordinates_are_422(client, params):
    assert client.get("/places/nearest", params=params).status_code == 422


def test_requires_login(app_client):
    from fastapi.testclient import TestClient

    anon = TestClient(app_client.app)
    assert anon.get("/places/nearest", params={"lat": LAT, "lng": LNG}).status_code == 401


def test_rate_limit_is_shared_with_search(client, monkeypatch):
    monkeypatch.setattr(places_api, "search_limiter", SlidingWindowLimiter(2))
    assert _get(client).status_code == 200
    assert client.get("/places/search", params={"q": "해운대"}).status_code == 200
    r = _get(client)
    assert r.status_code == 429 and r.json()["code"] == "RATE_LIMITED"


def test_db_failure_is_503_without_leaking_coordinates(client, monkeypatch, caplog):
    from sqlalchemy.exc import OperationalError

    def boom(*a, **kw):
        raise OperationalError(f"SELECT ... POINT({LNG} {LAT})", {"lat": LAT, "lng": LNG}, Exception("down"))

    monkeypatch.setattr(repository, "find_nearest", boom)
    with caplog.at_level(logging.DEBUG):
        r = _get(client)
    assert r.status_code == 503 and r.json()["code"] == "PLACES_UNAVAILABLE"
    assert str(LAT) not in caplog.text and str(LNG) not in caplog.text
    assert str(LAT) not in r.text


def test_coordinates_are_not_logged_or_stored(client, db_session, caplog):
    _add(db_session, "성수 한식당", 0.0001)
    before = db_session.execute(text("SELECT count(*) FROM places")).scalar_one()
    with caplog.at_level(logging.DEBUG):
        assert _get(client).status_code == 200
    assert str(LAT) not in caplog.text and str(LNG) not in caplog.text
    assert db_session.execute(text("SELECT count(*) FROM places")).scalar_one() == before   # 쓰기 없음


def test_uvicorn_access_log_drops_the_query_string_of_nearest_only():
    f = logguard.StripQueryFilter()

    def line(path):
        rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                                ("127.0.0.1:1", "GET", path, "1.1", 200), None)
        f.filter(rec)
        return rec.getMessage()

    redacted = line("/places/nearest?lat=37.5445&lng=127.0561")
    assert "37.5445" not in redacted and "127.0561" not in redacted and "[redacted]" in redacted
    assert "q=%EC%84%B1" in line("/places/search?q=%EC%84%B1")   # 다른 경로는 그대로
    assert line("/places/nearest") == '127.0.0.1:1 - "GET /places/nearest HTTP/1.1" 200'


def test_query_uses_the_gist_index(db_session):
    """ST_DWithin(geography)이 idx_places_geom을 탄다. 작은 테이블은 순차 스캔이 이기므로 끄고 계획만 본다."""
    for i in range(3):
        _add(db_session, f"가게{i}", 0.0001 * i)
    db_session.execute(text("SET LOCAL enable_seqscan = off"))
    stmt = repository._nearest_stmt(LAT, LNG, None, 100.0, 10)
    compiled = stmt.compile(dialect=db_session.get_bind().dialect, compile_kwargs={"literal_binds": True})
    plan = "\n".join(r[0] for r in db_session.execute(text("EXPLAIN " + str(compiled))))
    assert "idx_places_geom" in plan, plan
