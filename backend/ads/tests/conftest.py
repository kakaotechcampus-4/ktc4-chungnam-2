"""ads 테스트용 픽스처 — 실제 PostgreSQL(PostGIS)이 필요하다(docker-compose up -d). DB에 못 붙으면 pytest.fail.

- db_session: 테스트마다 트랜잭션을 열고 끝나면 롤백한다(join_transaction_mode="create_savepoint"). HTTP 테스트도 요청 세션을
  이 세션으로 바꿔 끼우므로 커밋이 밖으로 나가지 않는다.
- factory: 실제로 커밋하는 테스트(등록 스크립트의 main)용. 끝나면 ads 두 테이블을 통째로 비운다(#594). 그 테스트가 커밋한
  places 행은 테스트가 직접 지운다.
- World: 장소, 광고, 지도, 핀, 추천 run을 db_session에 넣는 도우미. 다른 모듈 테이블은 픽스처라서 모델로 직접 넣는다
  (테스트는 import 규칙 검사 대상이 아니다). ads 코드는 그 데이터를 각 모듈 api.py로만 읽는다.
"""

import os
import random
import re
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import auth.models  # noqa: F401
import common.events  # noqa: F401
import maps.models  # noqa: F401
import pins.models  # noqa: F401
import places.models  # noqa: F401
import recommend.models  # noqa: F401
import shortlist.models  # noqa: F401
from ads.models import Ad, AdDailyStat
from auth.testing import ensure_users
from common.database import Base
from maps.models import Map, Membership
from pins.models import Pin, Reaction
from places.models import Place, PlaceFact
from recommend.models import Candidate, RecommendRun

BASE_DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://pingo:pingo@localhost:5432/pingo")

# 세션(터미널)마다 다른 DB를 쓸 수 있게 한다. 예: PINGO_TEST_DB=pingo_test_ads pytest ads
TEST_DB_NAME = os.getenv("PINGO_TEST_DB", "pingo_test")
if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,62}", TEST_DB_NAME):
    raise RuntimeError(f"PINGO_TEST_DB={TEST_DB_NAME!r} — 영문·숫자·밑줄만 쓸 수 있다(63자 이하)")

SEONGSU = (37.5445, 127.0561)   # 조회 중심
NOW = datetime(2026, 11, 2, 3, 0, tzinfo=timezone.utc)   # 서울 12:00


def replace_dbname(url: str, dbname: str) -> str:
    root, _, _ = url.rpartition("/")
    return f"{root}/{dbname}"


@pytest.fixture(scope="session")
def test_engine():
    try:
        admin = sa.create_engine(replace_dbname(BASE_DATABASE_URL, "postgres"), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            if not conn.execute(sa.text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": TEST_DB_NAME}).first():
                conn.execute(sa.text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
        admin.dispose()
    except Exception as exc:  # noqa: BLE001 — 원인을 그대로 실패 메시지에 담아 올린다
        pytest.fail(f"테스트 DB({TEST_DB_NAME})를 준비하지 못했습니다 — docker-compose up -d 확인. 원인: {exc}")

    engine = sa.create_engine(replace_dbname(BASE_DATABASE_URL, TEST_DB_NAME))
    with engine.connect() as conn:
        conn.execute(sa.text("CREATE EXTENSION IF NOT EXISTS postgis"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    connection = test_engine.connect()
    outer = connection.begin()
    session = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")()
    yield session
    session.close()
    outer.rollback()
    connection.close()


@pytest.fixture()
def factory(test_engine):
    """실제로 커밋하는 sessionmaker. 끝나면 ads 두 테이블을 비운다(#594) — ads 테이블은 ads 테스트만 쓴다."""
    yield sessionmaker(bind=test_engine, autoflush=False)
    with test_engine.begin() as conn:
        conn.execute(sa.delete(AdDailyStat))
        conn.execute(sa.delete(Ad))


@pytest.fixture()
def rng():
    return random.Random(7)


class World:
    def __init__(self, db):
        self.db = db
        self.prefix = f"ads{uuid.uuid4().hex[:6]}"

    def uid(self, name: str) -> str:
        return f"{self.prefix}_{name}"

    def place(self, name: str, *, lat: float = SEONGSU[0], lng: float = SEONGSU[1], category: str = "카페",
              status: str = "open", kakao_place_id: str | None = None, kakao_place_url: str | None = None,
              address: str | None = "서울 성동구 성수동", can_recommend: bool = False) -> str:
        row = Place(source="permit", source_id=f"{self.prefix}-{uuid.uuid4().hex[:8]}", name=name, category=category,
                    address=address, geom=f"SRID=4326;POINT({lng} {lat})", status=status, can_recommend=can_recommend,
                    kakao_place_id=kakao_place_id, kakao_place_url=kakao_place_url)
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def ad(self, place_id: str, *, starts_at: datetime = NOW - timedelta(days=1),
           ends_at: datetime = NOW + timedelta(days=30), active: bool = True, memo: str | None = "광고주 계약 메모") -> str:
        row = Ad(place_id=place_id, starts_at=starts_at, ends_at=ends_at, active=active, memo=memo)
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def map(self, *, members=("u1", "u2")) -> str:
        uids = [self.uid(m) for m in members]
        ensure_users(self.db, *uids)
        row = Map(title="성수", start_date=date(2026, 12, 1), end_date=date(2026, 12, 2), created_by=uids[0])
        self.db.add(row)
        self.db.flush()
        for i, u in enumerate(uids):
            self.db.add(Membership(map_id=row.id, user_id=u, role="owner" if i == 0 else "member"))
        self.db.flush()
        return row.id

    def outsider(self, name: str = "stranger") -> str:
        ensure_users(self.db, self.uid(name))
        self.db.flush()
        return self.uid(name)

    def pin(self, map_id: str, place_id: str, *, category: str = "카페", by: str = "u1") -> str:
        row = Pin(id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct", source="db",
                  place_id=place_id, geom=sa.func.ST_SetSRID(sa.func.ST_MakePoint(SEONGSU[1], SEONGSU[0]), 4326),
                  visibility="public", created_by=self.uid(by))
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def live_pin(self, map_id: str, kakao_place_id: str, *, category: str = "카페", by: str = "u1") -> str:
        row = Pin(id=uuid.uuid4(), map_id=map_id, category=category, kind="일반", origin="direct", source="live",
                  kakao_place_id=kakao_place_id, search_query="검색어", visibility="public", created_by=self.uid(by))
        self.db.add(row)
        self.db.flush()
        return str(row.id)

    def delete_pin(self, pin_id: str) -> None:
        self.db.get(Pin, uuid.UUID(pin_id)).deleted_at = NOW
        self.db.flush()

    def against(self, pin_id: str, user: str, text: str = "너무 시끄러워요") -> None:
        self.db.add(Reaction(id=uuid.uuid4(), pin_id=uuid.UUID(pin_id), user_id=self.uid(user), type="against",
                             reason_text=text))
        self.db.flush()

    def fact(self, place_id: str, key: str, value) -> None:
        self.db.add(PlaceFact(place_id=uuid.UUID(place_id), fact_key=key, value=value, confidence="known", source_layer=1,
                              labeled_at=NOW))
        self.db.flush()

    def run(self, map_id: str, *, by: str, category: str = "카페", place_ids=(), created_at: datetime = NOW) -> str:
        row = RecommendRun(map_id=map_id, category=category, requested_by=self.uid(by), status="done",
                           created_at=created_at)
        self.db.add(row)
        self.db.flush()
        for rank, pid in enumerate(place_ids, start=1):
            self.db.add(Candidate(run_id=row.id, place_id=pid, lat=SEONGSU[0], lng=SEONGSU[1], rank=rank))
        self.db.flush()
        return str(row.id)

    def stats(self, ad_id: str) -> dict[date, tuple[int, int]]:
        rows = self.db.execute(sa.select(AdDailyStat).where(AdDailyStat.ad_id == uuid.UUID(ad_id))).scalars()
        return {r.stat_date: (r.served_count, r.click_count) for r in rows}


@pytest.fixture()
def world(db_session):
    return World(db_session)
