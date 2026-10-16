"""notifications 테스트용 픽스처 — 실제 PostgreSQL이 필요하다(docker-compose up -d).
DB에 못 붙으면 조용히 skip하지 않고 pytest.fail로 명확하게 실패시킨다.

agent/tests/conftest.py와 같은 트랜잭션 격리 패턴(join_transaction_mode="create_savepoint").
app_client는 DB 세션만 테스트 트랜잭션으로 바꿔 끼운다 — 알림 엔드포인트는 로그인만 보므로(멤버십 가드 없음)
다른 가짜가 필요 없다.
"""

import os
import re

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import auth.models  # noqa: F401 — 인증이 요청마다 users 행을 확인한다
import notifications.models  # noqa: F401 — Base.metadata에 알림 테이블을 등록시키기 위한 것
from auth.testing import ensure_users, session_cookie
from common.database import Base, get_db_session, session_scope

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")

# 세션(터미널)마다 다른 DB를 쓸 수 있게 한다 — 예: PINGO_TEST_DB=pingo_test_notif pytest notifications
TEST_DB_NAME = os.getenv("PINGO_TEST_DB", "pingo_test")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", TEST_DB_NAME):
    raise RuntimeError(f"PINGO_TEST_DB={TEST_DB_NAME!r} — 영문·숫자·밑줄만 쓸 수 있다(63자 이하)")


def replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session")
def test_engine():
    admin_url = replace_dbname(BASE_DATABASE_URL, "postgres")
    test_url = replace_dbname(BASE_DATABASE_URL, TEST_DB_NAME)
    try:
        admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": TEST_DB_NAME}).first()
            if not exists:
                conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin_engine.dispose()
    except Exception as exc:  # noqa: BLE001 — 원인을 그대로 실패 메시지에 담아 올린다
        pytest.fail(f"테스트 DB를 준비하지 못했습니다 — `docker-compose up -d`로 PostgreSQL이 떠 있는지 확인하세요. 원인: {exc}")

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
    """테스트마다 트랜잭션을 열고 끝나면 롤백한다 — 테스트 간 데이터가 섞이지 않는다."""
    connection = test_engine.connect()
    outer = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()

    yield session

    session.close()
    outer.rollback()
    connection.close()


@pytest.fixture()
def app_client(db_session):
    from fastapi.testclient import TestClient

    from main import app

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    ensure_users(db_session, "user_a", "user_b")

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def as_a():
    return session_cookie("user_a")


@pytest.fixture()
def as_b():
    return session_cookie("user_b")
