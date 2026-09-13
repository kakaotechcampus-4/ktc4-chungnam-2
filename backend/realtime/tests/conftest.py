"""service.py::replay용 픽스처 — 실제 PostgreSQL이 필요하다(docker-compose up -d).
DB에 못 붙으면 조용히 skip하지 않고 pytest.fail로 명확하게 실패시킨다.

pins/tests/conftest.py와 같은 트랜잭션 격리 패턴(join_transaction_mode="create_savepoint") —
자세한 이유는 그쪽 conftest.py 주석 참고.
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import common.events  # noqa: F401 — Base.metadata에 event_log를 등록시키기 위한 것
from common.database import Base

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
