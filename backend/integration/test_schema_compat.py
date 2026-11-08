"""이전 릴리스 호환 검사 — 이전 코드가 새 스키마에서 도는지 본다(#1464, deploy_rules.md 「스키마를 바꿀 때」).

`deploy.sh`는 마이그레이션을 먼저 올리고 앱을 바꾼다. 롤백은 앱만 이전 태그로 돌리고 DB는 그대로 둔다. 그래서 head 스키마는
이전 릴리스 코드도 받아야 한다(expand/contract). 이 규칙이 문서에만 있어 0062가 칸을 지우고 기본값을 지운 채 들어왔다(멘토 리뷰).

빈 DB에 head까지 올리고 두 모델과 비교한다.
- 이전 릴리스(최신 v 태그, 없으면 origin/main. `SCHEMA_COMPAT_BASE`로 바꿀 수 있다)의 모델:
  1. 이전 코드가 아는 테이블·칸이 DB에 있다(SELECT와 INSERT가 그 칸을 쓴다)
  2. 이전 코드가 모르는 NOT NULL 칸에는 DB 기본값이 있다(이전 코드의 INSERT는 그 칸을 넣지 않는다)
  3. 이전 코드에서 NULL을 허용하던 칸이 NOT NULL이 되지 않았다(이전 코드가 NULL을 넣을 수 있다)
- 지금 코드의 모델:
  4. 모델의 테이블·칸이 DB에 있다(마이그레이션 빠짐)
  5. 모델에 없는데 DB에 남은 테이블·칸은 deploy_rules.md 「지울 칸」 표에 있다. 표의 줄은 실제로 남은 것만 적는다

못 보는 것: 이전 코드의 raw SQL이 쓰는 칸, 이전 코드가 모르는 값, 칸의 뜻 변경. 리뷰로 본다.
두 모델은 각 코드의 `alembic/env.py`에 적힌 모델 import 목록으로 따로 띄운 프로세스에서 읽는다(같은 방법, 서로 섞이지 않게).
"""

import json
import os
import re
import subprocess
import sys
import tarfile
from io import BytesIO
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
DEPLOY_RULES = REPO / "deploy_rules.md"
BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")
MIG_DB = f"{os.getenv('PINGO_TEST_DB', 'pingo_test')}_schema_compat"[:63]
SYSTEM_TABLES = {"alembic_version", "spatial_ref_sys"}   # alembic과 PostGIS가 만든다. 모델이 아니다
RULES_HINT = "deploy_rules.md 「스키마를 바꿀 때」: 늘리기와 줄이기를 나눈다. 줄이기는 그 칸을 읽는 코드가 운영에서 빠진 다음 릴리스에 한다."

# 각 코드의 env.py가 import하는 모델을 올리고 테이블마다 칸의 nullable, 기본값 유무를 JSON으로 낸다.
_DUMP = r"""
import importlib, json, pathlib, re
from common.database import Base
env = pathlib.Path("alembic/env.py").read_text(encoding="utf-8")
for name in re.findall(r"^import (\S+)\s+# noqa: F401", env, re.M):
    importlib.import_module(name)
print(json.dumps({
    t.name: {c.name: {"nullable": bool(c.nullable), "default": c.server_default is not None} for c in t.columns}
    for t in Base.metadata.tables.values()
}))
"""


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, check=False)


def _base_ref() -> str:
    if ref := os.getenv("SCHEMA_COMPAT_BASE"):
        return ref
    tags = _git("tag", "-l", "v*", "--sort=-v:refname").stdout.decode().split()
    return tags[0] if tags else "origin/main"


def _dump_models(backend_dir: Path) -> dict[str, dict[str, dict]]:
    env = {**os.environ, "PYTHONPATH": str(backend_dir)}
    out = subprocess.run([sys.executable, "-c", _DUMP], cwd=backend_dir, env=env, capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, f"{backend_dir}의 모델을 읽지 못했다:\n{out.stderr[-3000:]}"
    return json.loads(out.stdout.strip().splitlines()[-1])


def _extract_backend(ref: str, dest: Path) -> Path:
    archive = _git("archive", "--format=tar", ref, "backend")
    if archive.returncode != 0:
        if os.getenv("CI"):
            pytest.fail(f"이전 릴리스 {ref}를 읽지 못했다(CI는 checkout fetch-depth: 0이 필요하다): {archive.stderr.decode()}")
        pytest.skip(f"이전 릴리스 {ref}가 이 저장소에 없다 — git fetch origin main --tags 뒤에 돈다")
    with tarfile.open(fileobj=BytesIO(archive.stdout)) as tar:
        tar.extractall(dest, filter="data")
    return dest / "backend"


def _pending_drops() -> set[str]:
    """deploy_rules.md 「지울 칸」 표의 첫 열(`테이블.칸` 또는 `테이블`)."""
    section = DEPLOY_RULES.read_text(encoding="utf-8").split("### 지울 칸", 1)
    assert len(section) == 2, "deploy_rules.md에 「### 지울 칸」 절이 없다"
    body = re.split(r"^#{2,3} ", section[1], maxsplit=1, flags=re.M)[0]
    return set(re.findall(r"^\|\s*`([a-z0-9_.]+)`\s*\|", body, re.M))


def _db_schema(url: str) -> dict[str, dict[str, dict]]:
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        return {
            t: {c["name"]: {"nullable": c["nullable"], "default": c.get("default") is not None or bool(c.get("identity"))}
                for c in inspector.get_columns(t)}
            for t in inspector.get_table_names() if t not in SYSTEM_TABLES
        }
    finally:
        engine.dispose()


def compat_problems(old: dict, db: dict) -> list[str]:
    """이전 릴리스 모델이 head DB에서 돌지 못하는 곳(위 1~3)."""
    problems = []
    for table, columns in old.items():
        if table not in db:
            problems.append(f"{table}: 이전 코드가 쓰는 테이블이 없다")
            continue
        for name, col in columns.items():
            if name not in db[table]:
                problems.append(f"{table}.{name}: 이전 코드가 쓰는 칸이 없다")
            elif col["nullable"] and not db[table][name]["nullable"]:
                problems.append(f"{table}.{name}: 이전 코드에서 NULL을 허용하던 칸이 NOT NULL이 됐다")
        for name, col in db[table].items():
            if name not in columns and not col["nullable"] and not col["default"]:
                problems.append(f"{table}.{name}: 이전 코드가 넣지 않는 NOT NULL 칸에 기본값이 없다")
    return problems


def drift_problems(current: dict, db: dict, pending: set[str]) -> list[str]:
    """지금 모델과 head DB가 어긋난 곳(위 4~5)."""
    problems, leftover = [], set()
    for table, columns in current.items():
        if table not in db:
            problems.append(f"{table}: 모델의 테이블이 DB에 없다(마이그레이션 빠짐)")
            continue
        problems += [f"{table}.{name}: 모델의 칸이 DB에 없다(마이그레이션 빠짐)" for name in columns if name not in db[table]]
        leftover |= {f"{table}.{name}" for name in db[table] if name not in columns}
    leftover |= {table for table in db if table not in current}
    problems += [f"{key}: 모델에 없는데 DB에 남았다 — deploy_rules.md 「지울 칸」 표에 줄이기 이슈와 함께 적는다" for key in sorted(leftover - pending)]
    problems += [f"{key}: 「지울 칸」 표에 있는데 DB에 남아 있지 않거나 모델이 다시 쓴다 — 표에서 지운다" for key in sorted(pending - leftover)]
    return problems


@pytest.fixture(scope="module")
def head_url():
    admin = sa.create_engine(f"{BASE_DATABASE_URL.rpartition('/')[0]}/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
        conn.execute(sa.text(f'CREATE DATABASE "{MIG_DB}"'))
    url = f"{BASE_DATABASE_URL.rpartition('/')[0]}/{MIG_DB}"
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    engine.dispose()
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url   # alembic/env.py가 읽는다
    try:
        cfg = Config()   # alembic.ini를 넘기지 않는다 — fileConfig가 다른 테스트의 로거를 끈다(agent/tests/test_migration.py)
        cfg.set_main_option("script_location", str(BACKEND / "alembic"))
        command.upgrade(cfg, "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous
        with admin.connect() as conn:
            conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
        admin.dispose()


def test_previous_release_code_runs_on_head_schema(head_url, tmp_path):
    ref = _base_ref()
    old = _dump_models(_extract_backend(ref, tmp_path))
    problems = compat_problems(old, _db_schema(head_url))
    assert not problems, f"이전 릴리스({ref}) 코드가 head 스키마에서 깨진다. {RULES_HINT}\n" + "\n".join(problems)


def test_current_models_match_head_schema_except_pending_drops(head_url):
    problems = drift_problems(_dump_models(BACKEND), _db_schema(head_url), _pending_drops())
    assert not problems, "지금 모델과 head 스키마가 어긋난다.\n" + "\n".join(problems)


def test_checks_catch_drop_and_default_removal():
    """0062가 한 두 가지(칸 삭제, 새 NOT NULL 칸의 기본값 제거)를 잡는지 — 검사 자체의 회귀 테스트."""
    old = {"runs": {"id": {"nullable": False, "default": False}, "pin_ids": {"nullable": False, "default": False}}}
    db = {"runs": {"id": {"nullable": False, "default": False}, "version": {"nullable": False, "default": False}}}
    assert compat_problems(old, db) == [
        "runs.pin_ids: 이전 코드가 쓰는 칸이 없다",
        "runs.version: 이전 코드가 넣지 않는 NOT NULL 칸에 기본값이 없다",
    ]
    db_expand = {"runs": {**old["runs"], "version": {"nullable": False, "default": True}}}
    assert compat_problems(old, db_expand) == []
    current = {"runs": {"id": {}, "version": {}}}
    assert drift_problems(current, db_expand, set()) == ["runs.pin_ids: 모델에 없는데 DB에 남았다 — deploy_rules.md 「지울 칸」 표에 줄이기 이슈와 함께 적는다"]
    assert drift_problems(current, db_expand, {"runs.pin_ids"}) == []
