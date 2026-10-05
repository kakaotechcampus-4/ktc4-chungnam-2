"""
자체 장소 DB 테스트용 픽스처 — 실제 PostgreSQL+PostGIS가 필요하다(docker-compose up -d).
DB에 못 붙으면 조용히 skip하지 않고 pytest.fail로 실패시킨다(docs/code-quality.md).
트랜잭션 격리는 pins/tests/conftest.py와 같은 방식(SAVEPOINT)이다. DB를 안 쓰는 테스트는 이 픽스처를 요청하지 않는다.
"""

import os
import re

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import places.models  # noqa: F401 — Base.metadata에 places/place_facts 등록
from common.database import Base

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")
TEST_DB_NAME = os.getenv("PINGO_TEST_DB", "pingo_test")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", TEST_DB_NAME):
    raise RuntimeError(f"PINGO_TEST_DB={TEST_DB_NAME!r} — 영문·숫자·밑줄만 쓸 수 있다(63자 이하)")


def _replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session")
def test_engine():
    try:
        admin = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            if not conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}).first():
                conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"테스트 DB를 준비하지 못했습니다 — `docker-compose up -d` 확인. 원인: {exc}")
    engine = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, TEST_DB_NAME))
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
