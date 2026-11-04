"""마이그레이션 0055_place_external_ids up/down — 0054_credit_ad_sessions까지 올린 DB에 번호표 두 테이블이 생기고 내려가면 사라진다. models.py와 어긋나지 않았는지도 본다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_extid_mig` DB를 따로 만들고 끝나면 지운다.
"""

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.script import ScriptDirectory

from places.models import PlaceExternalId, PlaceExternalIdVote
from places.tests import test_place_hours_migration as base
from places.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, _replace_dbname

REVISION = "0055_place_external_ids"
PREVIOUS = "0054_credit_ad_sessions"
MIG_DB = f"{TEST_DB_NAME}_extid_mig"[:63]


@pytest.fixture()
def mig_url(monkeypatch):
    admin = sa.create_engine(_replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}"'))
        conn.execute(sa.text(f'CREATE DATABASE "{MIG_DB}"'))
    url = _replace_dbname(BASE_DATABASE_URL, MIG_DB)
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
    engine.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    yield url
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
    admin.dispose()


def _tables(url):
    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        return {t: {c["name"] for c in insp.get_columns(t)} for t in ("place_external_ids", "place_external_id_votes") if insp.has_table(t)}
    finally:
        engine.dispose()


def test_revision_id_fits_and_follows_the_previous_head():
    assert len(REVISION) <= 32
    script = ScriptDirectory.from_config(base._config())
    assert len(script.get_heads()) == 1                      # 체인은 하나다. 뒤에 다른 마이그레이션이 붙어도 된다(0056, #1168)
    assert REVISION in {r.revision for r in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_creates_tables_matching_the_models_and_downgrade_drops_them(mig_url):
    cfg = base._config()
    command.upgrade(cfg, PREVIOUS)
    assert _tables(mig_url) == {}
    command.upgrade(cfg, "head")
    assert _tables(mig_url) == {
        "place_external_ids": set(PlaceExternalId.__table__.c.keys()),
        "place_external_id_votes": set(PlaceExternalIdVote.__table__.c.keys()),
    }
    engine = sa.create_engine(mig_url)
    with engine.begin() as conn:
        conn.execute(sa.text("INSERT INTO places (id, source, source_id, name, category, geom, status) VALUES "
                             "('00000000-0000-0000-0000-000000000001', 'permit', 'A', 'A', '음식점', ST_GeogFromText('POINT(127 37.5)'), 'open')"))
        conn.execute(sa.text("INSERT INTO place_external_ids (id, provider, external_id, place_id, source) VALUES "
                             "('00000000-0000-0000-0000-0000000000a1', 'naver', 'naver:1', '00000000-0000-0000-0000-000000000001', 'user')"))
        conn.execute(sa.text("INSERT INTO place_external_id_votes (external_id_row, voter_hash) VALUES ('00000000-0000-0000-0000-0000000000a1', 'h')"))
        with pytest.raises(sa.exc.IntegrityError):   # 같은 짝은 한 행
            conn.execute(sa.text("INSERT INTO place_external_ids (id, provider, external_id, place_id, source) VALUES "
                                 "('00000000-0000-0000-0000-0000000000a2', 'naver', 'naver:1', '00000000-0000-0000-0000-000000000001', 'hint')"))
    with engine.begin() as conn:
        conn.execute(sa.text("DELETE FROM places"))   # on delete cascade — 번호표와 표가 함께 지워진다
        assert conn.scalar(sa.text("SELECT count(*) FROM place_external_ids")) == 0
        assert conn.scalar(sa.text("SELECT count(*) FROM place_external_id_votes")) == 0
    engine.dispose()
    command.downgrade(cfg, PREVIOUS)
    assert _tables(mig_url) == {}
    command.upgrade(cfg, "head")
    assert set(_tables(mig_url)) == {"place_external_ids", "place_external_id_votes"}
