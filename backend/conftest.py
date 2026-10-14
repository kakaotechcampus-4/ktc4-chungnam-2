import os

# 테스트는 항상 test 환경이다. common.settings import보다 먼저 정해져야 해서 루트 conftest에 둔다.
# setdefault가 아니라 강제로 덮어쓴다 — 개발자 셸에 PINGO_ENV=prod가 남아있으면(예: 배포
# 스크립트를 돌리고 같은 터미널에서 바로 테스트를 돌리는 경우) setdefault는 그 값을 그대로
# 두어 테스트가 prod 가드에 걸려 깨진다(DeepSeek 검수 지적). 테스트는 셸 환경과 무관하게
# 항상 test여야 한다.
os.environ["PINGO_ENV"] = "test"

# 테스트 결과가 개발자 머신 상태(backend/.env, 셸에 남은 *_MODE)에 따라 달라지면 안 된다(#370) — CI와 같아야 한다.
# - 어댑터 모드는 dev로 강제한다. real을 쓰는 테스트는 monkeypatch로 직접 정한다.
# - backend/.env는 읽지 않는다(settings가 PINGO_LOAD_DOTENV=0이면 건너뛴다). 설정 테스트는 monkeypatch.delenv로
#   "아무것도 정하지 않은 상태"를 직접 만든다.
# - 예외: 실제 외부 API를 부르는 live 테스트는 .env의 키가 필요하다 — `PINGO_TEST_DOTENV=1 python -m pytest -m live ...`
os.environ["PLACES_MODE"] = "dev"
os.environ["LLM_MODE"] = "dev"
if os.environ.get("PINGO_TEST_DOTENV") != "1":
    os.environ["PINGO_LOAD_DOTENV"] = "0"


# ---- 새 DB에서도 postgis가 먼저 켜져 있게 한다 ----
# 전체 테스트 공통 준비 — pingo_test DB와 postgis 익스텐션이 **테스트 순서와 무관하게** 먼저 있게 한다.
# 
# 모듈별 conftest는 각자 `Base.metadata.create_all`을 부르는데, pytest는 수집 단계에서 모든 모듈의 models를
# import하므로 auth·realtime처럼 postgis를 안 켜는 conftest가 먼저 돌면 pins의 geography 컬럼 때문에
# 새 DB에서 "type geography does not exist"로 죽는다(로컬은 pingo_test가 남아 있어 가려져 있었다 — CI 첫 실행에서 발견).
# DB에 못 붙으면 조용히 넘어간다: 모듈 conftest가 자기 메시지로 실패한다.


import re

import pytest
import sqlalchemy as sa

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")

# 세션(터미널)마다 다른 DB를 쓸 수 있게 한다 — 여러 pytest가 같은 DB에서 create_all/drop_all을 하면 서로의
# 테이블을 지운다. 예: PINGO_TEST_DB=pingo_test_pins pytest pins. 지정 안 하면 기존과 같은 pingo_test.
TEST_DB_NAME = os.getenv("PINGO_TEST_DB", "pingo_test")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", TEST_DB_NAME):
    raise RuntimeError(f"PINGO_TEST_DB={TEST_DB_NAME!r} — 영문·숫자·밑줄만 쓸 수 있다(63자 이하)")


def _replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_db_with_postgis():
    try:
        admin = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            if not conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}).first():
                conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()
        engine = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, TEST_DB_NAME))
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.commit()
        engine.dispose()
    except Exception:  # noqa: BLE001 — 아래 이유로 삼킨다(모듈 conftest가 원인을 보고한다)
        pass
    yield


# ---- live 마커: 실제 외부 API를 부르는 테스트는 기본 실행에서 뺀다 ----
# 돌리려면 `PINGO_TEST_DOTENV=1 python -m pytest -m live places` (키가 .env에 있어야 하고, 구글 등은 과금된다).

def pytest_configure(config):
    config.addinivalue_line("markers", "live: 실제 외부 API를 호출한다(과금·키 필요). -m live 로만 실행된다")


def pytest_collection_modifyitems(config, items):
    if "live" in (config.getoption("-m") or ""):
        return
    skip = pytest.mark.skip(reason="live 테스트 — `-m live`로만 실행")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
