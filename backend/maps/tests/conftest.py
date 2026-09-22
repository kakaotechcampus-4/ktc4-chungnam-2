"""
test_maps_api.py·test_invites_api.py·test_membership_gateway.py·test_constraints.py용 픽스처.
backend/pins/tests/conftest.py를 그대로 복제하고 import·오버라이드만 바꿨다(실제
PostgreSQL+PostGIS 필요, docker-compose up -d).

app_client는 오버라이드가 2개다 — DB 세션뿐 아니라 authz.deps.get_membership_gateway도
maps.api.DbMembershipGateway로 바꿔 끼운다. 지금 authz/deps.py에 남아있는 AllowAllMembership
스텁(모두 'member' 취급)을 그대로 두면 "비구성원 404" 단언이 전부 무의미하게 통과하기
때문이다 — 이 오버라이드가 이 테스트 스위트의 핵심이다.
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import authz.deps
import common.events  # noqa: F401
import maps.models  # noqa: F401
from common.database import Base, session_scope
from maps.api import DbMembershipGateway

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
    from maps.deps import get_db_session

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    app.dependency_overrides[authz.deps.get_membership_gateway] = (
        lambda: DbMembershipGateway(db_session)
    )

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
