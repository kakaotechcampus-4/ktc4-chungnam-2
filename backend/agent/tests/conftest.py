"""agent 테이블 테스트용 픽스처 — 실제 PostgreSQL이 필요하다(docker-compose up -d).
DB에 못 붙으면 조용히 skip하지 않고 pytest.fail로 명확하게 실패시킨다.

realtime/tests/conftest.py와 같은 트랜잭션 격리 패턴(join_transaction_mode="create_savepoint"). 마이그레이션
테스트(test_migration.py)는 이 픽스처를 쓰지 않고 자기 DB를 따로 만든다.
"""

import os
import re

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from agent import flows
from agent.models import (
    AgentCursor,
    AgentReasonSummary,
    AgentRun,
    AgentRunAdvice,
    AgentSettings,
    AgentSuggestion,
    AgentSuggestionView,
)
# 스냅샷 테스트(test_snapshot.py)가 다른 모듈 테이블에 픽스처를 넣고 그 모듈의 api.py로 읽는다(#514)
import auth.models  # noqa: F401
import common.events  # noqa: F401
import maps.models  # noqa: F401
import pins.models  # noqa: F401
import places.models  # noqa: F401
import recommend.models  # noqa: F401
import shortlist.models  # noqa: F401
from common.database import Base

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")

# 세션(터미널)마다 다른 DB를 쓸 수 있게 한다 — 여러 pytest가 같은 DB에서 create_all/drop_all을 하면 서로의
# 테이블을 지운다. 예: PINGO_TEST_DB=pingo_test_agent pytest agent. 지정 안 하면 기존과 같은 pingo_test.
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
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))   # pins.geom
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


# FK 순서(열람 → 제안 → 나머지)
AGENT_TABLES = (
    AgentSuggestionView, AgentSuggestion, AgentRunAdvice, AgentReasonSummary, AgentRun, AgentCursor, AgentSettings,
)


@pytest.fixture()
def factory(test_engine):
    """실제로 커밋하는 테스트용 sessionmaker(world.py). 끝나면 agent_* 7개 테이블을 통째로 비운다(#594).

    world.cleanup은 자기 지도 행만 지우는데, run_tick은 event_log에 남은 다른 지도(예: 다른 모듈 테스트가 커밋하고
    남긴 map_race)도 잡아 관찰하고 agent_runs, agent_cursors를 커밋한다. 그 행이 뒤 테스트에 남지 않게 한다.
    agent_* 테이블은 agent 테스트만 쓰므로 통째로 비워도 다른 모듈 테스트에 영향이 없다."""
    yield sessionmaker(bind=test_engine, autoflush=False)

    with test_engine.begin() as conn:
        for model in AGENT_TABLES:
            conn.execute(sa.delete(model))


@pytest.fixture(autouse=True)
def _reset_daily_cleanup(monkeypatch):
    """하루 한 번 정리했는지(flows._cleanup_done_on)는 프로세스 메모리라 앞선 테스트의 run_tick이 오늘로 바꿔 둔다.
    테스트마다 처음 상태로 되돌린다(#594)."""
    monkeypatch.setattr(flows, "_cleanup_done_on", None)
