"""
통합 테스트 픽스처 — 모듈별 conftest와 달리 **아무것도 가짜로 바꿔 끼우지 않는다**(멤버십 게이트웨이
포함). 모듈 테스트는 FakeMembership으로 "구성원이라고 치고" 각자의 로직만 보는데, 여기서는 지도 생성
API가 만든 실제 memberships 행으로 인가가 통과되는지까지 본다. DB 세션만 테스트 트랜잭션으로 바꾼다
(테스트가 끝나면 롤백 — 다른 테스트와 데이터가 섞이지 않는다).

모든 모듈의 모델을 import하는 이유: Base.metadata.create_all이 그 시점에 등록된 테이블만 만든다.
"""

import os
import re

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import auth.models  # noqa: F401
import common.events  # noqa: F401
import maps.models  # noqa: F401
import pins.models  # noqa: F401
import places.models  # noqa: F401 — pins가 get_places(db)로 이름·URL을 읽고, recommend 통합 테스트가 자체 장소 DB를 쓴다
import recommend.models  # noqa: F401
import shortlist.models  # noqa: F401
from auth.models import User
from auth.testing import session_cookie
from common.database import Base, get_db_session, session_scope

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")

# 세션(터미널)마다 다른 DB를 쓸 수 있게 한다 — 여러 pytest가 같은 DB에서 create_all/drop_all을 하면 서로의
# 테이블을 지운다. 예: PINGO_TEST_DB=pingo_test_pins pytest pins. 지정 안 하면 기존과 같은 pingo_test.
TEST_DB_NAME = os.getenv("PINGO_TEST_DB", "pingo_test")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", TEST_DB_NAME):
    raise RuntimeError(f"PINGO_TEST_DB={TEST_DB_NAME!r} — 영문·숫자·밑줄만 쓸 수 있다(63자 이하)")


def _replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session")
def test_engine():
    admin_url = _replace_dbname(BASE_DATABASE_URL, "postgres")
    test_url = _replace_dbname(BASE_DATABASE_URL, TEST_DB_NAME)
    try:
        admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}
            ).first()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()
    except Exception as exc:  # noqa: BLE001 — 원인을 그대로 실패 메시지에 담아 올린다
        pytest.fail(f"테스트 DB({TEST_DB_NAME})를 준비하지 못했습니다 — docker-compose up -d 확인. 원인: {exc}")

    engine = sa.create_engine(test_url)
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
def fake_places(monkeypatch):
    """핀 생성은 places.api(match_place 등)만 거친다(#195). 자체 DB 적재 없이 FakePlaces 샘플 장소로 돌린다.
    통합 테스트가 가짜로 바꾸는 유일한 경계다."""
    from places.testing import FakePlaces

    return FakePlaces().install(monkeypatch)


@pytest.fixture()
def pin_body(fake_places):
    """FakePlaces 샘플 장소 키로 핀 생성 요청 본문을 만든다(검색 결과를 그대로 되돌려 보내는 것과 같다)."""

    def build(key: str, **override) -> dict:
        row = fake_places._row(fake_places.place_id(key))
        body = {"category": row.category, "place_id": f"kakao:{key}", "place_name": row.name,
                "lat": row.lat, "lng": row.lng}
        return {**body, **override}

    return build


@pytest.fixture()
def app_client(db_session, fake_places):
    from fastapi.testclient import TestClient

    from main import app

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture()
def two_users(db_session):
    """로그인해 있는 사용자 둘. 서명된 세션 쿠키를 돌려준다(#126)."""
    db_session.add(User(id="user_a", provider="kakao", provider_user_id="pa", display_name="철수"))
    db_session.add(User(id="user_b", provider="kakao", provider_user_id="pb", display_name="영희"))
    db_session.commit()
    return session_cookie("user_a"), session_cookie("user_b")
