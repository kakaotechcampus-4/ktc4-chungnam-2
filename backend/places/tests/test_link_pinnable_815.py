"""링크 가져오기가 내는 matches·address_candidates는 핀 생성이 받아 줄 곳만이다(#815) — 「핀 찍기」가 활성인데 PLACE_NOT_SUPPORTED가 나지 않게.
핀 생성은 matches의 place_id·이름·좌표·분류를 힌트로 match_place를 부른다(주소는 아직 안 보낸다). 실제 PostgreSQL+PostGIS."""

import pytest
from sqlalchemy import func

import main  # noqa: F401 — 순환 import 방지
from places import api
from places.models import Place
from places.schemas import PlaceHint

NID = "naver:1412566798"
MAP_URL = "https://map.naver.com/p/entry/place/1412566798"


def _add(db, sid, name, address, lng, category="음식점", kakao_place_id=None):
    p = Place(source="permit", source_id=sid, name=name, category=category, address=address, status="open", kakao_place_id=kakao_place_id,
              geom=func.ST_SetSRID(func.ST_MakePoint(lng, 37.54), 4326))
    db.add(p)
    db.flush()
    return str(p.id)


def _create_would_succeed(db, match):
    """핀 생성이 매칭 결과로 부르는 match_place — FE가 matches 항목의 값을 그대로 되돌려 보낸다."""
    hint = PlaceHint(match.place_id, match.place_name, match.lat, match.lng, match.category or "")
    return api.match_place(hint, db=db) is not None


def test_unambiguous_link_match_is_kept_and_creatable(db_session):
    pid = _add(db_session, "1", "성수 칼국수", "서울 성동구 성수이로 100", 127.05)
    api.record_external_id("naver", NID, pid, source="hint", db=db_session)
    r = api.parse_link(MAP_URL, db=db_session)
    assert [m.place_name for m in r.matches] == ["성수 칼국수"] and r.matched_by == "external_id" and r.needs_search_query is False
    assert _create_would_succeed(db_session, r.matches[0])


def test_match_whose_pin_creation_would_be_refused_is_dropped_so_the_live_pin_path_runs(db_session):
    """같은 이름의 점포가 30m 안에 둘 — 주소 없이는 어느 쪽인지 가를 수 없어 match_place가 거절한다. 그런 곳을 matches로 내보내면 안 된다."""
    a = _add(db_session, "1", "성수 칼국수", "서울 성동구 성수이로 100", 127.05)
    _add(db_session, "2", "성수 칼국수", "서울 성동구 성수이로 102", 127.05001)
    api.record_external_id("naver", NID, a, source="hint", db=db_session)
    own = api.own_places_by_external_id(NID, db=db_session)
    assert [c.place_id for c in own] == [a]   # 번호표는 신뢰하지만
    assert not _create_would_succeed(db_session, api._to_link_match(own[0]))   # 핀 생성은 이 힌트로 거절한다
    r = api.parse_link(MAP_URL, db=db_session)
    assert r.matches == [] and r.matched_by is None and r.needs_search_query is True   # → 호출 쪽이 실시간 핀 경로로 보낸다


def test_kakao_id_recorded_place_is_always_creatable_by_its_id(db_session):
    a = _add(db_session, "1", "성수 칼국수", "서울 성동구 성수이로 100", 127.05, kakao_place_id="kakao:555")
    _add(db_session, "2", "성수 칼국수", "서울 성동구 성수이로 102", 127.05001)
    r = api.parse_link("https://place.map.kakao.com/555", db=db_session)
    assert [m.place_id for m in r.matches] == ["kakao:555"] and _create_would_succeed(db_session, r.matches[0])


def test_hint_match_and_address_candidate_are_filtered_the_same_way(db_session):
    _add(db_session, "1", "법인명 카페", "서울특별시 종로구 창덕궁1길 39", 126.99, category="카페")
    assert [m.place_name for m in api.match_address_candidates("서울 종로구 창덕궁1길 39", db=db_session)] == ["법인명 카페"]
    _add(db_session, "2", "법인명 카페", "서울특별시 종로구 창덕궁1길 41", 126.99001, category="카페")   # 같은 이름이 가까이 — 주소 없이는 가를 수 없다
    assert api.match_address_candidates("서울 종로구 창덕궁1길 39", db=db_session) == []   # 후보가 핀 생성에서 거절될 곳이라 내보내지 않는다
    assert api.match_by_name_address("법인명 카페", "서울 종로구 창덕궁1길 39", db=db_session) == []
