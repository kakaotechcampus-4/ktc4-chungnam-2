import os

# 테스트는 항상 test 환경이다. common.settings import보다 먼저 정해져야 해서 루트 conftest에 둔다.
# setdefault가 아니라 강제로 덮어쓴다 — 개발자 셸에 PINGO_ENV=prod가 남아있으면(예: 배포
# 스크립트를 돌리고 같은 터미널에서 바로 테스트를 돌리는 경우) setdefault는 그 값을 그대로
# 두어 테스트가 prod 가드에 걸려 깨진다(DeepSeek 검수 지적). 테스트는 셸 환경과 무관하게
# 항상 test여야 한다.
os.environ["PINGO_ENV"] = "test"


# ---- 새 DB에서도 postgis가 먼저 켜져 있게 한다 ----
# 전체 테스트 공통 준비 — pingo_test DB와 postgis 익스텐션이 **테스트 순서와 무관하게** 먼저 있게 한다.
# 
# 모듈별 conftest는 각자 `Base.metadata.create_all`을 부르는데, pytest는 수집 단계에서 모든 모듈의 models를
# import하므로 auth·realtime처럼 postgis를 안 켜는 conftest가 먼저 돌면 pins의 geography 컬럼 때문에
# 새 DB에서 "type geography does not exist"로 죽는다(로컬은 pingo_test가 남아 있어 가려져 있었다 — CI 첫 실행에서 발견).
# DB에 못 붙으면 조용히 넘어간다: 모듈 conftest가 자기 메시지로 실패한다.


import pytest
import sqlalchemy as sa

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")


def _replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db_with_postgis():
    try:
        admin = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            if not conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = 'pingo_test'")).first():
                conn.execute(sa.text("CREATE DATABASE pingo_test"))
        admin.dispose()
        engine = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, "pingo_test"))
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.commit()
        engine.dispose()
    except Exception:  # noqa: BLE001 — 아래 이유로 삼킨다(모듈 conftest가 원인을 보고한다)
        pass
    yield
