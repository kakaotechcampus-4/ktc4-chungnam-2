"""마이그레이션 0037_agent_course_runs와 0050(하루 상한 인덱스 삭제, #976) up/down — 빈 DB에 올리고 내렸다 다시 올린다.
models.py와 어긋나지 않았는지도 본다.

`<PINGO_TEST_DB>_course_mig` DB를 따로 만들고 끝나면 지운다(agent/tests/test_migration.py와 같은 방식).
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from agent.course.models import AgentCourseRun
from agent.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname

BACKEND = Path(__file__).resolve().parents[3]
REVISION, PREVIOUS = "0037_agent_course_runs", "0036_ads"
DROP_INDEX_REVISION, DROP_INDEX_PREVIOUS = "0050_drop_course_user_index", "0049_reviews"
DROPPED_INDEX = "ix_agent_course_runs_user_created"   # 하루 상한을 세던 자리(0037). 상한이 크레딧으로 바뀌어(#950) 0050에서 지운다
MODEL_INDEXES = {i.name for i in AgentCourseRun.__table__.indexes}
MODE_REVISION, MODE_PREVIOUS = "0062_course_run_modes", "0061_recommend_run_origin"
MODE_COLUMNS = {"mode", "headline", "fixes", "checked", "snapshot_version"}    # 0062가 더한 칸
KEEP_REVISION = "0067_course_run_pin_ids_keep"   # snapshot_pin_ids를 줄이기(#1465) 전까지 남긴다(#1464)
KEPT_COLUMN = "snapshot_pin_ids"   # 모델에서는 뺐고 0067~0068 사이 DB에 남는다. 0069에서 지운다
DROP_PIN_IDS_REVISION = "0069_course_run_pin_ids_drop"   # #1465
MIG_DB = f"{TEST_DB_NAME}_course_mig"[:63]


@pytest.fixture()
def mig_url(monkeypatch):
    admin = sa.create_engine(replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        conn.execute(sa.text(f'CREATE DATABASE "{MIG_DB}"'))
    url = replace_dbname(BASE_DATABASE_URL, MIG_DB)
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
    admin.dispose()


def _config() -> Config:
    cfg = Config()   # alembic.ini를 넘기지 않는다 — 로깅 설정을 다시 하면 caplog 테스트가 깨진다(agent/tests/test_migration.py)
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_chain_has_one_head_and_contains_course_revisions():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert {REVISION, DROP_INDEX_REVISION} <= {r.revision for r in script.walk_revisions()}


def test_upgrade_matches_model_enforces_single_active_run_and_downgrades(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert {c["name"] for c in inspector.get_columns("agent_course_runs")} == (set(AgentCourseRun.__table__.columns.keys()) - MODE_COLUMNS) | {"snapshot_pin_ids"}   # 0037 시점 — 0062 전
        indexes = {i["name"]: i for i in inspector.get_indexes("agent_course_runs")}
        assert set(indexes) == MODEL_INDEXES | {DROPPED_INDEX}   # 0037 시점에는 0050에서 지울 인덱스가 아직 있다
        assert indexes["uq_agent_course_runs_active"]["unique"]

        insert = sa.text(
            "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at, snapshot_pin_ids)"
            " VALUES (gen_random_uuid(), 'm1', 'u1', :status, '{}', now(), '[]')"
        )
        with engine.begin() as conn:
            conn.execute(insert, {"status": "done"})
            conn.execute(insert, {"status": "failed"})
            conn.execute(insert, {"status": "running"})
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:   # 진행 중은 (지도, 요청자)당 하나
            conn.execute(insert, {"status": "queued"})

        command.downgrade(cfg, PREVIOUS)
        assert "agent_course_runs" not in set(sa.inspect(engine).get_table_names())
        command.upgrade(cfg, REVISION)
        assert "agent_course_runs" in set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _index_columns(engine) -> dict[str, list[str]]:
    return {i["name"]: i["column_names"] for i in sa.inspect(engine).get_indexes("agent_course_runs")}


def test_0050_drops_user_created_index_matches_model_and_downgrade_restores_it(mig_url):
    cfg = _config()
    command.upgrade(cfg, DROP_INDEX_PREVIOUS)
    engine = sa.create_engine(mig_url)
    try:
        before = _index_columns(engine)
        assert before[DROPPED_INDEX] == ["requested_by", "created_at"]

        command.upgrade(cfg, DROP_INDEX_REVISION)
        after = _index_columns(engine)
        assert set(after) == MODEL_INDEXES   # 모델과 DB가 같다
        assert DROPPED_INDEX not in after

        command.downgrade(cfg, DROP_INDEX_PREVIOUS)
        assert _index_columns(engine) == before   # 0037과 같은 모양으로 돌아온다
        command.upgrade(cfg, DROP_INDEX_REVISION)
        assert set(_index_columns(engine)) == MODEL_INDEXES
    finally:
        engine.dispose()


def test_0062_adds_mode_columns_backfills_old_rows_and_keeps_pin_ids(mig_url):
    cfg = _config()
    command.upgrade(cfg, MODE_PREVIOUS)
    engine = sa.create_engine(mig_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at, snapshot_pin_ids)"
                " VALUES (gen_random_uuid(), 'm1', 'u1', 'done', '{}', now(), '[\"a\"]')"))
        command.upgrade(cfg, MODE_REVISION)
        assert {c["name"] for c in sa.inspect(engine).get_columns("agent_course_runs")} == set(AgentCourseRun.__table__.columns.keys()) | {KEPT_COLUMN}
        with engine.begin() as conn:
            row = conn.execute(sa.text("SELECT mode, headline, fixes, checked, snapshot_version, snapshot_pin_ids FROM agent_course_runs")).one()
        assert tuple(row) == ("plan", None, [], [], "legacy", ["a"])   # 옛 run은 plan이고 version을 몰라 legacy(→ stale). 핀 id는 남는다(롤백용)
        command.downgrade(cfg, MODE_PREVIOUS)
        cols = {c["name"] for c in sa.inspect(engine).get_columns("agent_course_runs")}
        assert KEPT_COLUMN in cols and not (MODE_COLUMNS & cols)
        command.upgrade(cfg, MODE_REVISION)
    finally:
        engine.dispose()


def test_0067_restores_pin_ids_on_db_that_ran_old_0062_and_both_codes_insert(mig_url):
    """옛 0062(칸 삭제, 기본값 제거)를 돈 스테이징을 흉내 내고 0067이 맞추는지, 맞춘 뒤 이전 코드와 새 코드의 INSERT가 둘 다 되는지."""
    cfg = _config()
    command.upgrade(cfg, KEEP_REVISION)
    command.downgrade(cfg, MODE_REVISION)
    engine = sa.create_engine(mig_url)
    try:
        with engine.begin() as conn:   # 옛 0062가 한 일
            conn.execute(sa.text("ALTER TABLE agent_course_runs DROP COLUMN snapshot_pin_ids"))
            conn.execute(sa.text("ALTER TABLE agent_course_runs ALTER COLUMN snapshot_version DROP DEFAULT"))
            conn.execute(sa.text(
                "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at, snapshot_version)"
                " VALUES (gen_random_uuid(), 'm0', 'u1', 'done', '{}', now(), 'v0')"))
        command.upgrade(cfg, KEEP_REVISION)
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT snapshot_pin_ids FROM agent_course_runs WHERE map_id = 'm0'")).scalar_one() == []
            conn.execute(sa.text(   # 이전 코드: snapshot_pin_ids는 넣고 snapshot_version은 모른다
                "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at, snapshot_pin_ids)"
                " VALUES (gen_random_uuid(), 'm1', 'u1', 'done', '{}', now(), '[\"a\"]')"))
            conn.execute(sa.text(   # 새 코드: snapshot_version은 넣고 snapshot_pin_ids는 모른다
                "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at, snapshot_version)"
                " VALUES (gen_random_uuid(), 'm2', 'u1', 'done', '{}', now(), 'v1')"))
            rows = conn.execute(sa.text(
                "SELECT map_id, snapshot_version, snapshot_pin_ids FROM agent_course_runs WHERE map_id IN ('m1', 'm2') ORDER BY map_id")).all()
        assert [tuple(r) for r in rows] == [("m1", "legacy", ["a"]), ("m2", "v1", [])]
    finally:
        engine.dispose()


def test_0069_drops_pin_ids_and_snapshot_version_default_and_downgrades(mig_url):
    """줄이기(#1465): 칸이 모델과 같아지고, 새 코드의 INSERT는 그대로 되며, version 없는 INSERT는 이제 거부된다. downgrade는 0067 모양이다."""
    cfg = _config()
    command.upgrade(cfg, KEEP_REVISION)
    engine = sa.create_engine(mig_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text(
                "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at, snapshot_version)"
                " VALUES (gen_random_uuid(), 'm1', 'u1', 'done', '{}', now(), 'v1')"))
        command.upgrade(cfg, DROP_PIN_IDS_REVISION)
        assert {c["name"] for c in sa.inspect(engine).get_columns("agent_course_runs")} == set(AgentCourseRun.__table__.columns.keys())
        with engine.begin() as conn:
            assert conn.execute(sa.text("SELECT snapshot_version FROM agent_course_runs WHERE map_id = 'm1'")).scalar_one() == "v1"
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:   # 기본값이 없으니 version을 모르는 INSERT는 거부된다
            conn.execute(sa.text(
                "INSERT INTO agent_course_runs (id, map_id, requested_by, status, input, snapshot_at)"
                " VALUES (gen_random_uuid(), 'm2', 'u1', 'done', '{}', now())"))
        command.downgrade(cfg, KEEP_REVISION)
        with engine.begin() as conn:
            row = conn.execute(sa.text("SELECT snapshot_version, snapshot_pin_ids FROM agent_course_runs WHERE map_id = 'm1'")).one()
        assert tuple(row) == ("v1", [])   # 칸은 돌아오지만 지운 값은 없다
        command.upgrade(cfg, DROP_PIN_IDS_REVISION)
    finally:
        engine.dispose()
