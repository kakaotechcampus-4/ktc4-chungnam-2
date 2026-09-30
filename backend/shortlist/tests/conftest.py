"""
test_shortlist_api.py용 픽스처 — 실제 PostgreSQL+PostGIS가 필요하다(docker-compose up -d).
pins/tests/conftest.py와 동일 패턴(join_transaction_mode="create_savepoint") — 이유는 그쪽
docstring 참고. DB에 못 붙으면 조용히 skip하지 않고 pytest.fail로 명확하게 실패시킨다.

app_client는 오버라이드가 2개다 — DB 세션뿐 아니라 authz.deps.get_membership_gateway도
FakeMembership으로 바꿔 끼운다(이슈 #88, authz/for_Root.md의 "[루트 정정] ... 이슈
#87/#88/#89로 대체" 절 참고). `.env`의 MEMBERSHIP_MODE=real로 authz/deps.py의
get_membership_gateway가 이제 DbMembershipGateway(실제 memberships 테이블 조회)를 돌려주는데,
그 어댑터가 쓰는 DB 세션은 이 conftest의 테스트 트랜잭션이 아니라 별도 커넥션(common.database.
engine)이라 이 fixture가 memberships 행을 미리 넣어도 영원히 안 보인다 — 게다가 이 conftest는
maps.models를 import하지 않아 테스트 DB에 memberships 테이블 자체가 없다. 그래서 실제 행을
넣는 대신 게이트웨이 자체를 FakeMembership으로 갈아 끼운다(maps/tests/conftest.py와 같은 원리).
"""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import auth.models  # noqa: F401 — pins.api(get_pin_response_for_viewer)가 auth.api를 부른다
import common.events  # noqa: F401 — event_log 테이블 등록
import pins.models  # noqa: F401 — shortlist_items.pin_id FK 대상 + 테스트가 직접 핀을 심는다
import shortlist.models  # noqa: F401
from authz.deps import get_membership_gateway
from authz.testing import FakeMembership
from common.database import Base, session_scope

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

    Base.metadata.create_all(bind=engine)  # pins/reactions/shortlist_items/event_log 전부 등록됨

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
    from shortlist.deps import get_db_session

    def _override_get_db_session():
        with session_scope(db_session) as s:
            yield s

    app.dependency_overrides[get_db_session] = _override_get_db_session
    # 이 파일이 실제로 요청하는 (mapId, user_id) 조합만 "member"로 채운다 — map_2는 교차-지도
    # 테스트(Rule B)가 shortlist.loaders.load_pin_for_confirm 안에서 게이트웨이를 부르기 전에
    # 이미 404로 끝내버려서(경로 mapId≠핀의 실제 map_id) 여기 등록될 일이 없다.
    app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership(
        {("map_1", "user_1"): "member", ("map_1", "user_2"): "member"}
    )

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()
