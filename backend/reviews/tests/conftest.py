"""reviews 테스트 픽스처 — 실제 PostgreSQL(PostGIS)이 필요하다(docker-compose up -d). DB에 못 붙으면 pytest.fail.

- db_session: 테스트마다 트랜잭션을 열고 끝나면 롤백한다(join_transaction_mode="create_savepoint"). HTTP 테스트도 요청 세션을
  이 세션으로 바꿔 끼우므로 커밋이 밖으로 나가지 않는다.
- World: 사용자, 지도, 핀, 후기를 db_session에 넣는 도우미. 다른 모듈 테이블은 픽스처라서 모델로 직접 넣는다(테스트는 import 규칙
  검사 대상이 아니다). reviews 코드는 그 데이터를 각 모듈 api.py로만 읽는다.
"""

import os
import re
import uuid
from datetime import date

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import auth.models  # noqa: F401
import common.events  # noqa: F401 — main.py의 lifespan이 event_log를 읽는다
import credits.models  # noqa: F401
import maps.models  # noqa: F401
import pins.models  # noqa: F401
import places.models  # noqa: F401
import reviews.models  # noqa: F401
from auth.testing import create_guest, ensure_users, session_cookie
from common.database import Base, session_scope
from maps.models import Map, Membership
from pins.models import Pin
from places.models import Place
from reviews.models import Review

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")

# 세션(터미널)마다 다른 DB를 쓸 수 있게 한다. 예: PINGO_TEST_DB=pingo_test_reviews pytest reviews
TEST_DB_NAME = os.getenv("PINGO_TEST_DB", "pingo_test")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", TEST_DB_NAME):
    raise RuntimeError(f"PINGO_TEST_DB={TEST_DB_NAME!r} — 영문·숫자·밑줄만 쓸 수 있다(63자 이하)")

SEONGSU = (37.5445, 127.0561)


def replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session")
def test_engine():
    try:
        admin = sa.create_engine(replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            if not conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}).first():
                conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()
    except Exception as exc:  # noqa: BLE001 — 원인을 그대로 실패 메시지에 담아 올린다
        pytest.fail(f"테스트 DB({TEST_DB_NAME})를 준비하지 못했습니다 — docker-compose up -d 확인. 원인: {exc}")

    engine = sa.create_engine(replace_dbname(BASE_DATABASE_URL, TEST_DB_NAME))
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    connection = test_engine.connect()
    outer = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    yield session
    session.close()
    outer.rollback()
    connection.close()


@pytest.fixture()
def app_client(db_session):
    from common.database import get_db_session
    from main import app

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


class World:
    def __init__(self, db, app):
        self.db = db
        self.app = app
        self.prefix = f"rv{uuid.uuid4().hex[:6]}"

    def uid(self, name: str) -> str:
        return f"{self.prefix}_{name}"

    def user(self, name: str) -> str:
        ensure_users(self.db, self.uid(name))
        self.db.flush()
        return self.uid(name)

    def guest(self, name: str = "guest") -> str:
        return create_guest(self.db, self.uid(name)).id

    def place(self, name: str = "성수 칼국수") -> str:
        row = Place(source="permit", source_id=f"{self.prefix}-{uuid.uuid4().hex[:8]}", name=name, category="음식점",
                    address="서울 성동구 성수동", geom=f"SRID=4326;POINT({SEONGSU[1]} {SEONGSU[0]})", status="open")
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def map(self, *members: str) -> str:
        """members는 World.user/guest가 돌려준 id. 첫 사람이 방장."""
        row = Map(title="성수", start_date=date(2026, 12, 1), end_date=date(2026, 12, 2), created_by=members[0])
        self.db.add(row)
        self.db.flush()
        for i, u in enumerate(members):
            self.db.add(Membership(map_id=row.id, user_id=u, role="owner" if i == 0 else "member"))
        self.db.flush()
        return row.id

    def pin(self, map_id: str, place_id: str, *, by: str) -> str:
        row = Pin(id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct", source="db",
                  place_id=place_id, geom=sa.func.ST_SetSRID(sa.func.ST_MakePoint(SEONGSU[1], SEONGSU[0]), 4326),
                  visibility="public", created_by=by)
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def live_pin(self, map_id: str, *, by: str) -> str:
        row = Pin(id=uuid.uuid4(), map_id=map_id, category="음식점", kind="일반", origin="direct", source="live",
                  kakao_place_id=f"kakao:{uuid.uuid4().hex[:6]}", search_query="성수 곱창", visibility="public",
                  created_by=by)
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def review(self, place_id: str, user_id: str, *, rating: int = 4, body: str = "맛있어요") -> str:
        """HTTP를 거치지 않고 후기 행만 넣는다(보상 없음)."""
        row = Review(place_id=place_id, user_id=user_id, rating=rating, body=body)
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def client(self, user_id: str) -> TestClient:
        self.db.commit()   # 바깥 트랜잭션 안의 세이브포인트 — 요청 세션이 같은 연결로 본다
        return TestClient(self.app, cookies=session_cookie(user_id))


@pytest.fixture()
def world(db_session, app_client):
    return World(db_session, app_client.app)
