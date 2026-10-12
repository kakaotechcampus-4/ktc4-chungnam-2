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
import re

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import auth.models  # noqa: F401 — maps.service가 auth.api를 부르면서 users 테이블도 있어야 한다
import authz.deps
import common.events  # noqa: F401
import maps.models  # noqa: F401
import pins.models  # noqa: F401 — shortlist_items.pin_id가 pins.id를 FK로 참조한다
import recommend.models  # noqa: F401 — 지도 나가기(#369)가 그 지도의 근거 줄을 지운다
import shortlist.models  # noqa: F401 — maps.service가 shortlist.api를 부르면서 필요해짐
from auth.testing import ensure_users
from common.database import Base, session_scope
from maps.api import DbMembershipGateway

# 이 모듈 테스트가 쿠키로 로그인시키는 사용자 id 전부
TEST_USER_IDS = ("user_1", "user_2", "user_3", "outsider", "user_lonely")

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
        pytest.fail(
            "테스트 DB를 준비하지 못했습니다 — `docker-compose up -d`로 "
            f"PostgreSQL이 떠 있는지 확인하세요. 원인: {exc}"
        )

    engine = sa.create_engine(test_url)
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.commit()
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"{TEST_DB_NAME} DB에 postgis 익스텐션을 켤 수 없습니다: {exc}")

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

    ensure_users(db_session, *TEST_USER_IDS)   # 인증이 요청마다 users 행을 확인한다(#126)

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
