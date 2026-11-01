"""credits 테스트 픽스처 — 실제 PostgreSQL이 필요하다(docker-compose up -d). DB에 못 붙으면 pytest.fail.

- db_session: 테스트마다 트랜잭션을 열고 끝나면 롤백한다(join_transaction_mode="create_savepoint"). HTTP 테스트도 요청 세션을
  이 세션으로 바꿔 끼우므로 커밋이 밖으로 나가지 않는다.
- factory: 실제로 커밋하는 테스트(동시 첫 차감)용. 끝나면 그 테스트가 쓴 사용자의 credits 행을 지운다(#594). 사용자 id는
  `committed_user`가 고유하게 만든다.
"""

import os
import re
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import auth.models  # noqa: F401 — users 행(게스트 판정, 인증)
import common.events  # noqa: F401 — main.py의 lifespan이 event_log를 읽는다
import credits.models  # noqa: F401
from common.database import Base, session_scope
from credits.models import CreditAccount, CreditLedger

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")

# 세션(터미널)마다 다른 DB를 쓸 수 있게 한다. 예: PINGO_TEST_DB=pingo_test_credits pytest credits
TEST_DB_NAME = os.getenv("PINGO_TEST_DB", "pingo_test")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", TEST_DB_NAME):
    raise RuntimeError(f"PINGO_TEST_DB={TEST_DB_NAME!r} — 영문·숫자·밑줄만 쓸 수 있다(63자 이하)")


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
def committed_user(test_engine):
    """커밋하는 테스트용 사용자 id(users 행 없음 = 게스트 아님). 끝나면 그 사람의 credits 행을 지운다."""
    user_id = f"credits_{uuid.uuid4().hex[:8]}"
    yield user_id
    with test_engine.begin() as conn:
        conn.execute(sa.delete(CreditLedger).where(CreditLedger.user_id == user_id))
        conn.execute(sa.delete(CreditAccount).where(CreditAccount.user_id == user_id))


@pytest.fixture()
def factory(test_engine):
    return sessionmaker(bind=test_engine, autoflush=False)


@pytest.fixture()
def app_client(db_session):
    from fastapi.testclient import TestClient

    from common.database import get_db_session
    from main import app

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()
