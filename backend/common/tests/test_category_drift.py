"""
common/categories.py(카테고리 정의 한 곳, #280)와 카테고리 목록을 따로 들고 있는 곳들을 대조한다.
authz/tests/test_policy_drift.py와 같은 방식 — 정의를 바꾸고 다른 곳을 안 고치면 여기서 실패한다.

- docs/api-spec.yaml: Category = 전체, RecommendCategory = recommendable (순서까지)
- DB enum(마이그레이션 체인 head): category = 전체, place_category = pinnable, recommend_category = recommendable.
  모델의 Enum은 common.categories에서 만들므로 모델만 보면 늘 같다 — 실제 DB 값은 마이그레이션이 정하므로
  새 DB에 `alembic upgrade head`를 돌려 pg_enum을 읽는다. 순서는 보지 않는다(값 추가는 ADD VALUE로 끝에 붙는다).
- contracts/mocks/categories.ts: CATEGORY_RULES가 성질까지 같은지
- 남은 코드가 카테고리 이름과 직접 비교하지 않는지(`category == "숙소"` 같은 분기가 다시 생기지 않게)
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
import sqlalchemy as sa
import yaml

from common import categories

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
MOCK_CATEGORIES = REPO / "contracts" / "mocks" / "categories.ts"


def _spec_enum(name: str) -> list[str]:
    spec = yaml.safe_load((REPO / "docs" / "api-spec.yaml").read_text(encoding="utf-8"))
    return spec["components"]["schemas"][name]["enum"]


def test_spec_category_matches_all_categories():
    assert _spec_enum("Category") == list(categories.all_categories())


def test_spec_recommend_category_matches_recommendable():
    assert _spec_enum("RecommendCategory") == list(categories.recommendable())


# ---- DB enum: 마이그레이션 head의 실제 값 ----

_DB_ENUMS = {
    "category": categories.all_categories,          # pins.category
    "place_category": categories.pinnable,          # places.category
    "recommend_category": categories.recommendable,  # recommend_runs·exclusions.category
}


def _with_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="module")
def migrated_enum_values() -> dict[str, set[str]]:
    """빈 DB를 만들어 마이그레이션 체인을 끝까지 올리고 enum 값을 읽는다. 다 읽으면 DB를 지운다."""
    base_url = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")
    dbname = f"{os.getenv('PINGO_TEST_DB', 'pingo_test')}_categories"
    admin = sa.create_engine(_with_dbname(base_url, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}"'))
        conn.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    url = _with_dbname(base_url, dbname)
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
            conn.commit()
        # alembic env.py가 logging 설정을 바꾸므로 다른 테스트에 번지지 않게 별도 프로세스로 돌린다
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND, env={**os.environ, "DATABASE_URL": url, "PINGO_ENV": "test"},
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        assert result.returncode == 0, f"alembic upgrade head 실패:\n{result.stderr[-2000:]}"
        with engine.connect() as conn:
            rows = conn.execute(
                sa.text(
                    "SELECT t.typname, e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                    "WHERE t.typname = ANY(:names)"
                ),
                {"names": list(_DB_ENUMS)},
            ).all()
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}"'))
        admin.dispose()
    values: dict[str, set[str]] = {name: set() for name in _DB_ENUMS}
    for typname, label in rows:
        values[typname].add(label)
    return values


@pytest.mark.parametrize("enum_name", list(_DB_ENUMS))
def test_db_enum_matches_registry(migrated_enum_values, enum_name):
    """다르면 마이그레이션을 추가해야 한다(값을 더할 땐 ALTER TYPE ... ADD VALUE)."""
    assert migrated_enum_values[enum_name] == set(_DB_ENUMS[enum_name]())


# ---- contracts 목 서버 ----

_MOCK_RULE = re.compile(
    r"^\s*(\S+): \{ pinnable: (true|false), reactable: (true|false), recommendable: (true|false) \},?\s*$",
    flags=re.MULTILINE,
)


def test_mock_server_category_rules_match():
    text = MOCK_CATEGORIES.read_text(encoding="utf-8")
    declared = [
        (name, pinnable == "true", reactable == "true", recommendable == "true")
        for name, pinnable, reactable, recommendable in _MOCK_RULE.findall(text)
    ]
    expected = [(r.name, r.pinnable, r.reactable, r.recommendable) for r in categories.RULES]
    assert declared == expected, "contracts/mocks/categories.ts CATEGORY_RULES를 common/categories.py와 맞춘다"


# ---- 카테고리 이름으로 분기하는 코드가 다시 생기지 않게 ----

_NAMES = "|".join(categories.all_categories())
_NAME_BRANCH = re.compile(rf"category\s*(?:===?|!==?|(?:not\s+)?in)\s*[\(\[\{{]?\s*[\"'](?:{_NAMES})[\"']")
# 테스트·마이그레이션(과거 기록)은 보지 않는다. 정의 파일 자신도 뺀다.
_SKIP_PARTS = {"tests", "integration", "alembic", "node_modules", "__pycache__", ".venv", "venv"}


def _source_files():
    for root, pattern in ((BACKEND, "*.py"), (REPO / "contracts" / "mocks", "*.ts")):
        for path in root.rglob(pattern):
            if _SKIP_PARTS.isdisjoint(path.relative_to(REPO).parts) and not path.name.endswith(".test.ts"):
                yield path


def test_no_branch_on_category_name():
    """「숙소면 막는다」 같은 분기는 성질(reactable 등)을 묻게 한다 — 이름으로 분기하면 정의를 바꿔도 조용히 남는다."""
    hits = [
        f"{path.relative_to(REPO).as_posix()}:{lineno}: {line.strip()}"
        for path in _source_files()
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _NAME_BRANCH.search(line)
    ]
    assert hits == [], "카테고리 이름으로 분기하지 말고 common/categories.py의 성질을 쓴다:\n" + "\n".join(hits)
