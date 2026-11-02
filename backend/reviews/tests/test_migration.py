"""마이그레이션 0049_reviews up/down — 빈 DB에 0049까지 올리고, 0048로 내렸다가 다시 올린다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_reviews_mig` DB를 따로 만들고 끝나면 지운다.
models.py와 마이그레이션이 어긋나지 않았는지(칸 이름, CHECK, UNIQUE, 부분 인덱스, 신고의 CASCADE)도 여기서 본다.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from reviews.constants import REVIEW_BODY_MAX
from reviews.models import Review, ReviewReport
from reviews.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0049_reviews"
PREVIOUS = "0048_credits"
MODELS = (Review, ReviewReport)
TABLES = {m.__tablename__ for m in MODELS}
MIG_DB = f"{TEST_DB_NAME}_reviews_mig"[:63]


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
    monkeypatch.setenv("DATABASE_URL", url)  # alembic/env.py가 읽는다

    yield url

    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
    admin.dispose()


def _config() -> Config:
    # alembic.ini를 넘기지 않는다 — env.py의 fileConfig가 다른 테스트의 로거를 끈다(ads/tests/test_migration.py와 같은 이유)
    cfg = Config()
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_chain_has_one_head_and_contains_the_reviews_revision():
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(_config())
    assert len(script.get_heads()) == 1
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_creates_tables_matching_models_and_downgrade_removes_them(mig_url):
    cfg = _config()
    command.upgrade(cfg, REVISION)
    engine = sa.create_engine(mig_url)
    try:
        inspector = sa.inspect(engine)
        assert TABLES <= set(inspector.get_table_names())
        for model in MODELS:
            columns = {c["name"] for c in inspector.get_columns(model.__tablename__)}
            assert columns == set(model.__table__.columns.keys()), model.__tablename__
        assert inspector.get_foreign_keys("reviews") == []   # place_id·user_id에 FK를 걸지 않는다(#760)
        [fk] = inspector.get_foreign_keys("review_reports")
        assert (fk["referred_table"], fk["options"].get("ondelete")) == ("reviews", "CASCADE")

        [index] = [i for i in inspector.get_indexes("reviews") if i["name"] == "ix_reviews_place_created"]
        assert index["column_names"][0] == "place_id"
        assert "hidden_at IS NULL" in index["dialect_options"]["postgresql_where"]
        assert [u["column_names"] for u in inspector.get_unique_constraints("reviews")] == [["place_id", "user_id"]]

        insert = sa.text("INSERT INTO reviews (id, place_id, user_id, rating, body) "
                         "VALUES (gen_random_uuid(), :place, 'u1', :rating, :body)")
        with engine.begin() as conn:
            conn.execute(insert, {"place": "p1", "rating": 5, "body": "가" * REVIEW_BODY_MAX})
            review_id = conn.execute(sa.text("SELECT id FROM reviews")).scalar_one()
            conn.execute(sa.text("INSERT INTO review_reports (review_id, reporter_id) VALUES (:r, 'u2')"), {"r": review_id})
        for params in ({"place": "p1", "rating": 4, "body": "두 번째"},                    # 한 사람 한 장소에 하나
                       {"place": "p2", "rating": 0, "body": "별점"},                        # 1~5
                       {"place": "p3", "rating": 6, "body": "별점"},
                       {"place": "p4", "rating": 3, "body": ""},                            # 1자 이상
                       {"place": "p5", "rating": 3, "body": "가" * (REVIEW_BODY_MAX + 1)}):   # 상한
            with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
                conn.execute(insert, params)
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO review_reports (review_id, reporter_id) VALUES (:r, 'u2')"), {"r": review_id})
        with engine.begin() as conn:
            conn.execute(sa.text("DELETE FROM reviews"))
            assert conn.execute(sa.text("SELECT count(*) FROM review_reports")).scalar_one() == 0   # CASCADE

        command.downgrade(cfg, PREVIOUS)
        assert not (TABLES & set(sa.inspect(engine).get_table_names()))

        command.upgrade(cfg, REVISION)
        assert TABLES <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
