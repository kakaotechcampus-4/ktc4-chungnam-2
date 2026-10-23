"""마이그레이션 0039_user_identities up/down(#694) — 카카오 사용자의 수단을 user_identities로 옮기고 users의 세 칸을 지운다.
게스트는 수단을 만들지 않는다. 내려가면 수단이 users로 돌아가고 수단이 없는 사용자는 게스트가 된다. models.py와 어긋나지 않았는지도 본다.

다른 테스트와 테이블을 섞지 않도록 `<PINGO_TEST_DB>_uid_mig` DB를 따로 만들고 끝나면 지운다.
"""

from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from auth.models import User, UserIdentity
from auth.tests.conftest import BASE_DATABASE_URL, TEST_DB_NAME, _replace_dbname

BACKEND = Path(__file__).resolve().parents[2]
REVISION = "0039_user_identities"
PREVIOUS = "0038_place_hours"
MIG_DB = f"{TEST_DB_NAME}_uid_mig"[:63]


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
    monkeypatch.setenv("DATABASE_URL", url)   # alembic/env.py가 읽는다
    yield url
    with admin.connect() as conn:
        conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{MIG_DB}" WITH (FORCE)'))
    admin.dispose()


def _config() -> Config:
    cfg = Config()   # alembic.ini를 넘기지 않는다 — env.py가 fileConfig로 로깅을 다시 설정해 caplog 테스트를 깨뜨린다
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def _run(url, sql, **params):
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            result = conn.execute(sa.text(sql), params)
            return result.all() if result.returns_rows else None
    finally:
        engine.dispose()


def _columns(url, table):
    engine = sa.create_engine(url)
    try:
        insp = sa.inspect(engine)
        return {c["name"] for c in insp.get_columns(table)} if insp.has_table(table) else None
    finally:
        engine.dispose()


def test_chain_has_a_single_head_and_this_revision_follows_place_hours():
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS


def test_upgrade_moves_kakao_identities_and_drops_the_user_columns_then_downgrade_restores_them(mig_url):
    cfg = _config()
    command.upgrade(cfg, PREVIOUS)
    _run(mig_url, """
        INSERT INTO users (id, provider, provider_user_id, display_name, is_guest, guest_invite_token, created_at) VALUES
          ('k1', 'kakao', '1001', '철수', false, NULL, '2026-10-01T00:00:00+00:00'),
          ('k2', 'kakao', '1002', '영희', false, NULL, '2026-10-02T00:00:00+00:00'),
          ('g1', 'guest', 'random-token', '손님', true, 'tok', '2026-10-03T00:00:00+00:00')
    """)

    command.upgrade(cfg, REVISION)

    assert _columns(mig_url, "users") == set(User.__table__.c.keys())   # provider·provider_user_id·is_guest가 없다
    assert _columns(mig_url, "user_identities") == set(UserIdentity.__table__.c.keys())
    assert sorted(_run(mig_url, "SELECT user_id, provider, provider_user_id, created_at::date::text FROM user_identities")) == [
        ("k1", "kakao", "1001", "2026-10-01"), ("k2", "kakao", "1002", "2026-10-02"),
    ]
    assert _run(mig_url, "SELECT id, guest_invite_token FROM users WHERE id = 'g1'") == [("g1", "tok")]
    with pytest.raises(sa.exc.IntegrityError):   # 카카오 계정 하나는 사람 하나에만
        _run(mig_url, "INSERT INTO user_identities (id, user_id, provider, provider_user_id) "
                      "VALUES (gen_random_uuid(), 'g1', 'kakao', '1001')")
    with pytest.raises(sa.exc.IntegrityError):   # 한 사람에 카카오는 하나
        _run(mig_url, "INSERT INTO user_identities (id, user_id, provider, provider_user_id) "
                      "VALUES (gen_random_uuid(), 'k1', 'kakao', '9999')")
    # 게스트 전환(수단을 붙임) 뒤에 되돌려도 그 사용자는 카카오 사용자로 돌아간다
    _run(mig_url, "INSERT INTO user_identities (id, user_id, provider, provider_user_id) VALUES (gen_random_uuid(), 'g1', 'kakao', '1003')")
    _run(mig_url, "INSERT INTO users (id, display_name) VALUES ('g2', '새 손님')")

    command.downgrade(cfg, PREVIOUS)

    assert _columns(mig_url, "user_identities") is None
    assert {"provider", "provider_user_id", "is_guest"} <= _columns(mig_url, "users")
    rows = dict((r[0], r[1:]) for r in _run(mig_url, "SELECT id, provider, provider_user_id, is_guest FROM users"))
    assert rows["k1"] == ("kakao", "1001", False) and rows["k2"] == ("kakao", "1002", False)
    assert rows["g1"] == ("kakao", "1003", False)
    assert rows["g2"][0] == "guest" and rows["g2"][1] and rows["g2"][2] is True
    with pytest.raises(sa.exc.IntegrityError):   # uq_users_provider_identity도 돌아왔다
        _run(mig_url, "INSERT INTO users (id, provider, provider_user_id, display_name) VALUES ('k3', 'kakao', '1001', 'x')")

    command.upgrade(cfg, REVISION)   # 다시 올라간다
    assert len(_run(mig_url, "SELECT 1 FROM user_identities")) == 3
