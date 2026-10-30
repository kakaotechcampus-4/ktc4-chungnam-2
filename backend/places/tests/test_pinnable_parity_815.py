"""검색의 pinnable과 핀 생성의 match_place가 같은 답을 낸다(#815) — 「pinnable=true면 핀 생성이 된다」. 실제 PostgreSQL+PostGIS.

핀 생성 요청은 주소를 안 보낼 수도 있다(화면은 아직 안 보낸다). 그래서 pinnable은 주소 없이도 매칭될 때만 true다."""

import pytest
from sqlalchemy import select

from places import api, ingest, repository
from places.models import Place
from places.schemas import PlaceHint

ADDRESS = "서울특별시 종로구 율곡로 49-4"


def _own(db, *rows):
    repository.upsert_places(db, [ingest.PlaceRow("permit", sid, name, "음식점", addr, None, 37.5760, 126.9850, "open") for sid, name, addr in rows])
    db.flush()


def _hint(name, address, kakao_place_id="kakao:1"):
    return PlaceHint(kakao_place_id, name, 37.5760, 126.9850, "음식점", address)


def _create_would_succeed(db, hint):
    """핀 생성이 부르는 match_place — 주소를 보냈든 안 보냈든 모두 성공해야 pinnable=true가 옳다."""
    return [api.match_place(h, db=db) is not None for h in (hint, PlaceHint(hint.kakao_place_id, hint.name, hint.lat, hint.lng, hint.category, None))]


def test_oreno_ramen_is_not_pinnable_when_only_the_address_rescues_it(db_session):
    _own(db_session, ("O1", "오레노 라멘안국", ADDRESS))
    hint = _hint("오레노라멘 인사점", "서울 종로구 율곡로 49-4")
    with_address, without_address = _create_would_succeed(db_session, hint)
    assert (with_address, without_address) == (True, False)   # 화면이 주소를 안 보내면 핀 생성은 422였다
    assert api.pinnable_flags([hint], db=db_session) == [False]


@pytest.mark.parametrize("name, address", [
    ("오레노 라멘안국", ADDRESS),                 # 이름이 같다 — 주소 없이도 된다
    ("오레노 라멘안국 본점", None),
    ("전혀 다른 가게", ADDRESS),                  # 같은 건물의 다른 가게
    ("오레노 라멘안국", "서울 종로구 율곡로 99"),   # 같은 이름·다른 번지
])
def test_pinnable_flag_agrees_with_every_way_a_pin_request_can_come(db_session, name, address):
    _own(db_session, ("O1", "오레노 라멘안국", ADDRESS))
    hint = _hint(name, address)
    flag = api.pinnable_flags([hint], db=db_session)[0]
    if flag:
        assert all(_create_would_succeed(db_session, hint))   # 불변식: pinnable=true → 핀 생성 성공
    assert db_session.execute(select(Place.kakao_place_id)).scalars().all() == [None]   # 읽기만 한다


def test_pinnable_true_when_name_matches_even_without_address(db_session):
    _own(db_session, ("O1", "오레노 라멘안국", ADDRESS))
    assert api.pinnable_flags([_hint("오레노 라멘안국", ADDRESS)], db=db_session) == [True]
