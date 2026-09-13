"""
test_pins_api.py용 픽스처 — 실제 PostgreSQL+PostGIS가 필요하다(docker-compose up -d).
DB에 못 붙으면 조용히 skip하지 않고 pytest.fail로 명확하게 실패시킨다
(docs/code-quality.md: 실패를 감추는 코드를 만들지 않는다).

트랜잭션 격리: 이제 앱 코드(service.py)는 커밋하지 않지만 common.database.get_db는 여전히
요청마다 커밋하므로 격리가 계속 필요하다. SQLAlchemy 2.0이 문서화한 방식을 쓴다 —
join_transaction_mode="create_savepoint"로 세션을 만들면 세션의 commit()이 SAVEPOINT만
해제하고 바깥 트랜잭션(outer)은 살아있다(직접 실행해 확인, mentor-review-plan.md). 이전의
커스텀 after_transaction_end 리스너보다 짧고, 앱이 실제 commit()이나 begin_nested()
(방어 코드 2)를 걸어도 안전하게 살아남는다.
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import common.events  # noqa: F401
import pins.models  # noqa: F401
from common.database import Base, session_scope

# 위 두 import는 Base.metadata에 테이블(pins/reactions, event_log)을 등록시키기 위한 것 —
# 직접 쓰이진 않는다. event_log는 test_permissions_contract.py 등이 이벤트 발행을 검증할 때 쓴다.

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

    Base.metadata.create_all(bind=engine)  # common.events.EventLog까지 포함 — 전체 등록된 테이블

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
    from pins.deps import get_db_session

    def _override_get_db_session():
        # session_scope는 db.close()를 부르지 않는다(바깥 finally만 닫는다, common/database.py
        # 확인 완료) — 그래서 이 오버라이드가 끝난 뒤에도 db_session 픽스처로 계속 조회할 수 있다.
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
