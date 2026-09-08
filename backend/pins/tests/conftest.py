"""
test_pins_api.py용 픽스처 — 실제 PostgreSQL+PostGIS가 필요하다(docker-compose up -d).
DB에 못 붙으면 조용히 skip하지 않고 pytest.fail로 명확하게 실패시킨다
(docs/code-quality.md: 실패를 감추는 코드를 만들지 않는다).

이 저장소 전체에 conftest.py·pytest 설정이 아직 없어 pins가 처음 만든다.
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import pins.models  # noqa: F401
from common.database import Base

# 위 import는 Base.metadata에 테이블을 등록시키기 위한 것 — 직접 쓰이진 않는다.

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")


def _replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session")
def test_engine():
    admin_url = _replace_dbname(BASE_DATABASE_URL, "postgres")
    test_url = _replace_dbname(BASE_DATABASE_URL, "pingo_test")

    try:
        admin_engine = sa.create_engine(admin_url, isolation_level="AUTOCOMMIT")
        with admin_engine.connect() as conn:
            exists = conn.execute(
                sa.text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": "pingo_test"}
            ).first()
            if not exists:
                conn.execute(sa.text("CREATE DATABASE pingo_test"))
        admin_engine.dispose()
    except Exception as exc:  # noqa: BLE001 — 원인을 그대로 실패 메시지에 담아 올린다
        pytest.fail(
            "테스트 DB(pingo_test)를 준비하지 못했습니다 — `docker-compose up -d`로 "
            f"PostgreSQL이 떠 있는지 확인하세요. 원인: {exc}"
        )

    engine = sa.create_engine(test_url)
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"pingo_test DB에 postgis 익스텐션을 켤 수 없습니다: {exc}")

    Base.metadata.create_all(
        bind=engine, tables=[pins.models.Pin.__table__, pins.models.Reaction.__table__]
    )

    yield engine

    Base.metadata.drop_all(
        bind=engine, tables=[pins.models.Reaction.__table__, pins.models.Pin.__table__]
    )
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """테스트마다 트랜잭션을 열고 끝나면 롤백한다 — 테스트 간 데이터가 섞이지 않는다.

    service.py가 라우터 안에서 실제로 db.commit()을 부르므로, 단순 connection.begin()만으로는
    그 commit()이 바깥 트랜잭션까지 끝내버려 마지막 rollback()이 무력해진다. SQLAlchemy가
    문서화한 SAVEPOINT 패턴(외부 트랜잭션 안에 중첩 트랜잭션을 두고, 세션이 커밋할 때마다
    SAVEPOINT를 다시 연다)으로 격리한다.
    """
    connection = test_engine.connect()
    outer_transaction = connection.begin()
    session = sessionmaker(bind=connection)()

    nested = connection.begin_nested()

    @sa.event.listens_for(session, "after_transaction_end")
    def _restart_savepoint(sess, trans):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    outer_transaction.rollback()
    connection.close()


@pytest.fixture()
def app_client(db_session):
    from fastapi.testclient import TestClient

    from main import app
    from pins.deps import get_db_session

    def _override_get_db_session():
        yield db_session

    app.dependency_overrides[get_db_session] = _override_get_db_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
