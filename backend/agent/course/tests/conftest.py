"""AI 코스 짜기 DB·HTTP 테스트용 픽스처 — 실제 PostgreSQL이 필요하다(docker-compose up -d). 엔진 단위 테스트(test_runner 등)는 DB를 쓰지 않는다.

agent/tests/conftest.py의 엔진·롤백 세션을 그대로 쓰고(test_engine, db_session), 커밋하는 sessionmaker(factory)만 코스 테이블을 비우도록
바꾼다. 지도·핀·확정 항목은 agent/tests/world.py를 그대로 쓴다. 다른 모듈의 places는 api 함수를 대역으로 바꿔 좌표·이름·라벨을 넣는다.
"""

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from agent.course.gateways import CourseLlm, get_course_llm, get_session_factory
from agent.course.models import AgentCourseRun
from agent.tests.conftest import db_session, test_engine  # noqa: F401 — 픽스처 재노출
from agent.tests.world import World, real_now
from auth.testing import session_cookie
from common.database import get_db_session, session_scope
from places import api as places_api
from places.schemas import FactLabel, PlaceInfo


@pytest.fixture()
def factory(test_engine):
    """실제로 커밋하는 sessionmaker. 끝나면 agent_course_runs를 통째로 비운다(이 테이블은 코스 테스트만 쓴다)."""
    yield sessionmaker(bind=test_engine, autoflush=False)
    with test_engine.begin() as conn:
        conn.execute(sa.delete(AgentCourseRun))


@pytest.fixture()
def world(factory):
    w = World(factory, real_now())
    yield w
    w.cleanup()


class Places:
    """places.api.get_places·get_facts 대역. add(place_id, 이름, 위도, 경도, 분류, 라벨들)."""

    def __init__(self):
        self.infos: dict[str, PlaceInfo] = {}
        self.labels: dict[str, list[FactLabel]] = {}

    def add(self, place_id: str, name: str, lat: float, lng: float, category: str = "관광지", labels=()):
        self.infos[place_id] = PlaceInfo(place_id, name, lat, lng, category, None, None)
        self.labels[place_id] = [FactLabel(key, True, "known") for key in labels]

    def get_places(self, place_ids, *, db=None):
        return {pid: self.infos[pid] for pid in place_ids if pid in self.infos}

    def get_facts(self, place_ids, *, db=None):
        return {pid: self.labels.get(pid, []) for pid in place_ids}


@pytest.fixture()
def places(monkeypatch):
    p = Places()
    monkeypatch.setattr(places_api, "get_places", p.get_places)
    monkeypatch.setattr(places_api, "get_facts", p.get_facts)
    return p


def confirmed_map(world: World, places: Places, n: int = 4, *, members=("u1", "u2"), live: int = 0, **kw) -> tuple[str, list[str]]:
    """확정 핀 n개(자체 DB 장소, 서로 가깝다)와 실시간 확정 핀 live개가 있는 지도. (map_id, 핀 id 목록)."""
    map_id = world.map(members=members, **kw)
    ids = []
    for i in range(1, n + 1):
        pid = f"place_{map_id[:6]}_{i}"
        category = ("관광지", "카페", "음식점")[i % 3]
        places.add(pid, f"장소{i}", 37.5665 + i * 0.001, 126.978 + i * 0.001, category, labels=("is_indoor",) if i % 2 == 0 else ())
        ids.append(world.pin(map_id, category=category, place_id=pid))
    for i in range(live):
        ids.append(world.live_pin(map_id, f"실시간{i}"))
    for k, pin_id in enumerate(ids):
        world.confirm(map_id, pin_id, hours_ago=100 - k * 0.1)       # 확정 순서 = 핀 순서(added_at이 겹치면 순서가 정해지지 않는다)
    return map_id, ids


@pytest.fixture()
def client(world):
    """사용자 이름을 받아 그 사람의 TestClient를 돌려준다. 코스 백그라운드는 world의 sessionmaker를 쓴다.
    `client.llm = CourseLlm(...)`처럼 이름 붙은 속성으로 모델 대역을 바꿀 수 있다(기본은 모델 없음)."""
    from main import app

    state = {"llm": CourseLlm(goals_planner=None, direct_planner=None)}

    def _db():
        with world.factory() as db, session_scope(db) as s:
            yield s

    app.dependency_overrides[get_db_session] = _db
    app.dependency_overrides[get_session_factory] = lambda: world.factory
    app.dependency_overrides[get_course_llm] = lambda: state["llm"]
    made = []

    def as_user(name: str) -> TestClient:
        c = TestClient(app, cookies=session_cookie(world.uid(name)))
        made.append(c)
        return c

    as_user.set_llm = lambda llm: state.update(llm=llm)
    yield as_user
    for c in made:
        c.close()
    for dep in (get_db_session, get_session_factory, get_course_llm):
        app.dependency_overrides.pop(dep, None)
