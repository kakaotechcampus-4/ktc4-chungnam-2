"""마이그레이션 0043_places_name_norm up/down — 이미 있던 행의 name_norm이 채워지고 인덱스가 생기며 내려가면 사라진다.

같은 임시 DB 픽스처(`<PINGO_TEST_DB>_hrs_mig`)를 쓴다 — 다른 테스트와 테이블을 섞지 않는다."""

import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from places.tests.test_place_hours_migration import _config, mig_url  # noqa: F401 — 같은 임시 DB 픽스처(이름만 다르게 쓴다)

REVISION = "0043_places_name_norm"
PREVIOUS = "0042_places_trgm_search"


def test_chain_has_a_single_head_and_this_revision_follows_the_trigram_search():
    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_fills_existing_rows_and_creates_the_index_and_downgrade_removes_them(mig_url):  # noqa: F811
    cfg = _config()
    command.upgrade(cfg, PREVIOUS)
    engine = sa.create_engine(mig_url)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO places (id, source, source_id, name, category, geom, status) VALUES "
                             "('00000000-0000-0000-0000-000000000001', 'permit', 'A', '오레노 라멘(안국)', '음식점', ST_GeogFromText('POINT(127 37.5)'), 'open')"))
    command.upgrade(cfg, REVISION)
    with engine.begin() as conn:
        assert conn.scalar(sa.text("SELECT name_norm FROM places")) == "오레노라멘"
        assert conn.scalar(sa.text("SELECT count(*) FROM pg_indexes WHERE indexname = 'idx_places_name_norm'")) == 1
    command.downgrade(cfg, PREVIOUS)
    with engine.begin() as conn:
        assert conn.scalar(sa.text("SELECT count(*) FROM pg_indexes WHERE indexname = 'idx_places_name_norm'")) == 0
        assert "name_norm" not in {c["name"] for c in sa.inspect(conn).get_columns("places")}
    engine.dispose()
