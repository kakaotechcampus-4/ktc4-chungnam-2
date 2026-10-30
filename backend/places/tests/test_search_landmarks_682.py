"""대표 장소 검색과 문화시설(#682) — 「경복궁」「낙산공원」「국립민속박물관」「아르코예술극장」을 치면 본체가 맨 위에 온다.
카카오 응답은 CT1을 관광지로 읽고, 자체 DB에 짝이 있으면 pinnable=true. 실제 PostgreSQL+PostGIS, 카카오는 문서 모양 대역."""

import main  # noqa: F401 — 순환 import 방지
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from places import api, ingest, repository, router
from places.models import Place
from places.ratelimit import SlidingWindowLimiter
from places.service import PlaceService, to_result
from places.sources.kakao import KakaoPlaceSource
from places.tests.helpers import KAKAO_DOC, json_response, make_http

USER = SimpleNamespace(user_id="u1")
LANDMARKS = {   # 이름: (위도, 경도, 카카오 분류 코드)
    "경복궁": (37.5796, 126.9770, "AT4"),
    "낙산공원": (37.5806, 127.0074, "AT4"),
    "국립민속박물관": (37.5815, 126.9812, "CT1"),
    "아르코예술극장": (37.5817, 127.0034, "CT1"),
}


@pytest.fixture(autouse=True)
def _limiter(monkeypatch):
    monkeypatch.setattr(api, "search_limiter", SlidingWindowLimiter(1000))


def _own(db, **names):
    rows = [ingest.PlaceRow("tourapi", f"T{i}", n, "관광지", "서울특별시 종로구 1", None, *LANDMARKS[n][:2], "open") for i, n in enumerate(names)]
    repository.upsert_places(db, rows)
    db.flush()


def _kakao_docs(query):
    """카카오 정확도 순 응답을 흉내 낸다 — 본체와 매표소 같은 부속 시설이 섞여 있다."""
    lat, lng, code = LANDMARKS[query]
    return [
        {**KAKAO_DOC, "id": "1", "place_name": f"{query} 매표소", "category_group_code": code, "x": str(lng), "y": str(lat + 0.0001), "address_name": "서울 종로구 9"},
        {**KAKAO_DOC, "id": "2", "place_name": query, "category_group_code": code, "x": str(lng), "y": str(lat), "address_name": "서울 종로구 1"},
    ]


@pytest.fixture()
def kakao(monkeypatch):
    def install(query):
        http, _, _ = make_http(json_response({"documents": _kakao_docs(query)}))
        svc = PlaceService([KakaoPlaceSource(http, "k")])
        monkeypatch.setattr(api, "_is_dev", lambda: False)
        monkeypatch.setattr(api, "_service", lambda: svc)
    return install


def _search(db, q):
    lat, lng, _ = LANDMARKS[q]
    return router.search_places(q=q, lat=lat, lng=lng, limit=10, user=USER, db=db)


@pytest.mark.parametrize("name", list(LANDMARKS))
def test_the_landmark_itself_comes_first_and_is_pinnable_from_our_db(db_session, kakao, name):
    _own(db_session, **{name: None})
    kakao(name)
    out = _search(db_session, name)
    own_id = f"own:{db_session.execute(select(Place.id).where(Place.name == name)).scalar_one()}"
    assert out[0].place_id == own_id and out[0].pinnable is True and out[0].category == "관광지"
    assert out[0].place_source.provider == "tourapi"
    assert not any(r.place_name == name and r.place_id != own_id for r in out)   # 카카오의 같은 가게는 중복으로 안 나온다


@pytest.mark.parametrize("name", list(LANDMARKS))
def test_even_when_not_in_our_db_kakao_main_place_keeps_its_rank_and_is_a_tourist_spot(db_session, kakao, name):
    kakao(name)
    out = _search(db_session, name)
    main_place = next(r for r in out if r.place_name == name)
    assert main_place.category == "관광지"
    assert main_place.pinnable is False      # 짝이 없으면 핀을 못 찍는다(실시간 핀 경로)
    assert [r.place_name for r in out][0] == f"{name} 매표소"   # 카카오 순서 그대로 — 우리가 임의로 바꾸지 않는다


def test_kakao_culture_result_with_a_partner_in_our_db_is_pinnable(db_session):
    """CT1 문서가 관광지로 읽히고, 같은 장소가 자체 DB에 있으면 pinnable=true(핀 생성과 같은 판정)."""
    _own(db_session, 국립민속박물관=None)
    http, _, _ = make_http(json_response({"documents": [_kakao_docs("국립민속박물관")[1]]}))
    [found] = KakaoPlaceSource(http, "k").search_by_name(query="국립민속박물관", lat=None, lng=None, limit=5)
    assert found.category == "관광지"
    result = to_result(found)
    router._fill_pinnable([result], db_session)
    assert result.pinnable is True
