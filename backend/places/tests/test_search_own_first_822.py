"""장소 검색은 자체 DB 장소를 먼저(#822) — 카카오 상위권에 없어도 자체 DB 장소가 맨 앞에 온다. 실제 PostgreSQL+PostGIS."""

from types import SimpleNamespace

import pytest
from sqlalchemy import select

import main  # noqa: F401 — router보다 먼저 불러야 auth↔authz 순환 import가 풀린다
from common.errors import AppError
from places import api, ingest, repository, router
from places.models import Place
from places.ratelimit import SlidingWindowLimiter
from places.schemas import PlaceSearchResult

USER = SimpleNamespace(user_id="u1")


def _row(source_id, name, lat=37.5760, lng=126.9850, category="음식점", address="서울특별시 종로구 율곡로 1", status="open"):
    return ingest.PlaceRow("permit", source_id, name, category, address, None, lat, lng, status)


def _add(db, *rows, curated=()):
    repository.upsert_places(db, list(rows))
    for sid in curated:
        db.execute(Place.__table__.update().where(Place.source_id == sid).values(curated=True))
    db.flush()


def _kakao(pid, name, lat=37.5700, lng=126.9900, category="음식점"):
    return PlaceSearchResult(place_id=pid, place_name=name, lat=lat, lng=lng, category=category, address="서울 종로구 어딘가 9")


@pytest.fixture(autouse=True)
def _limiter(monkeypatch):
    monkeypatch.setattr(api, "search_limiter", SlidingWindowLimiter(1000))


@pytest.fixture()
def kakao(monkeypatch):
    """가짜 카카오 소스 — 부른 횟수를 센다."""
    state = SimpleNamespace(results=[], calls=0, fail=False)

    def fake(query, near, limit):
        state.calls += 1
        if state.fail:
            raise AppError("PLACES_UNAVAILABLE")
        return [r.model_copy() for r in state.results]

    monkeypatch.setattr(api, "search_by_name", fake)
    return state


def _search(db, q="안국", limit=10, lat=None, lng=None):
    return router.search_places(q=q, lat=lat, lng=lng, limit=limit, user=USER, db=db)


def _pid(db, source_id):
    return f"own:{db.execute(select(Place.id).where(Place.source_id == source_id)).scalar_one()}"


def test_own_db_place_not_in_kakao_top_comes_first(db_session, kakao):
    _add(db_session, _row("A1", "도토리가든 안국점"))
    kakao.results = [_kakao("kakao:1", "안국역 3호선"), _kakao("kakao:2", "안국 약국")]
    out = _search(db_session)
    assert out[0].place_id == _pid(db_session, "A1")
    assert out[0].pinnable is True and out[0].place_source.provider == "permit"
    assert [r.place_id for r in out[1:]] == ["kakao:1", "kakao:2"]


def test_kakao_not_called_when_own_db_fills_the_limit(db_session, kakao):
    _add(db_session, *[_row(f"B{i}", f"안국 식당{i}", lat=37.5760 + i * 0.001) for i in range(3)])
    out = _search(db_session, limit=3)
    assert len(out) == 3 and kakao.calls == 0


def test_kakao_fills_only_the_remaining_slots(db_session, kakao):
    _add(db_session, _row("C1", "안국 식당"))
    kakao.results = [_kakao(f"kakao:{i}", f"다른 곳{i}") for i in range(5)]
    out = _search(db_session, limit=3)
    assert [r.place_id for r in out][1:] == ["kakao:0", "kakao:1"] and len(out) == 3


def test_kakao_result_for_the_same_shop_is_dropped(db_session, kakao):
    _add(db_session, _row("D1", "도토리가든 안국점"))
    kakao.results = [_kakao("kakao:9", "도토리가든 안국점", lat=37.5761, lng=126.9851), _kakao("kakao:8", "딴 곳")]
    out = _search(db_session)
    assert [r.place_id for r in out] == [_pid(db_session, "D1"), "kakao:8"]


def test_closed_places_are_excluded(db_session, kakao):
    _add(db_session, _row("E1", "안국 폐업집"))
    db_session.execute(Place.__table__.update().where(Place.source_id == "E1").values(status="closed"))
    db_session.flush()
    assert _search(db_session) == []


def test_place_pick_match_rejects_is_not_listed_as_pinnable(db_session, kakao):
    # 같은 이름의 점포가 30m 안에 둘이면 핀 생성의 매칭이 모호해서 거절한다 → 검색에도 싣지 않는다
    _add(db_session, _row("F1", "안국 칼국수", lat=37.5760, lng=126.9850), _row("F2", "안국 칼국수", lat=37.57602, lng=126.98502))
    assert [r for r in _search(db_session) if r.place_id.startswith("own:")] == []


def test_name_match_before_address_match_and_curated_first(db_session, kakao):
    _add(
        db_session,
        _row("G1", "일반 식당", address="서울 종로구 안국동 1", lat=37.5770),
        _row("G2", "안국 일반", lat=37.5780),
        _row("G3", "안국 정예", lat=37.5790),
        curated=["G3"],
    )
    out = _search(db_session)
    assert [r.place_id for r in out] == [_pid(db_session, s) for s in ("G3", "G2", "G1")]


def test_nearer_first_when_coordinates_given(db_session, kakao):
    _add(db_session, _row("H1", "안국 먼곳", lat=37.5900), _row("H2", "안국 가까운곳", lat=37.5761))
    out = _search(db_session, lat=37.5760, lng=126.9850)
    assert [r.place_id for r in out] == [_pid(db_session, "H2"), _pid(db_session, "H1")]


def test_kakao_failure_still_returns_own_results(db_session, kakao):
    _add(db_session, _row("I1", "안국 식당"))
    kakao.fail = True
    assert [r.place_id for r in _search(db_session)] == [_pid(db_session, "I1")]


def test_kakao_failure_without_own_results_is_503(db_session, kakao):
    kakao.fail = True
    with pytest.raises(AppError) as e:
        _search(db_session)
    assert e.value.code == "PLACES_UNAVAILABLE"


def test_no_results_is_an_empty_list(db_session, kakao):
    assert _search(db_session, q="없는가게") == []


def test_like_wildcards_in_query_are_literal(db_session, kakao):
    _add(db_session, _row("J1", "안국 식당"))
    assert _search(db_session, q="%") == []


def test_pinnable_places_behind_many_rejected_ones_still_fill_the_limit(db_session, kakao):
    # 이름 순으로 앞선 네 쌍(8곳)은 동명 점포가 붙어 있어 pick_match가 거절한다 — 뒤의 핀 가능한 곳으로 limit을 채우고 카카오는 안 부른다
    pairs = [r for i in range(4) for r in (
        _row(f"P{i}a", f"안국 쌍{i}", lat=37.5700 + i * 0.01), _row(f"P{i}b", f"안국 쌍{i}", lat=37.5700 + i * 0.01 + 0.00002))]
    singles = [_row(f"S{i}", f"안국 홑{i}", lat=37.5500 + i * 0.01) for i in range(3)]
    _add(db_session, *pairs, *singles)
    out = _search(db_session, limit=3)
    assert [r.place_id for r in out] == [_pid(db_session, f"S{i}") for i in range(3)]
    assert kakao.calls == 0


def test_kakao_result_with_the_recorded_kakao_id_is_the_same_shop_even_when_name_and_place_differ(db_session, kakao):
    _add(db_session, _row("K1", "오레노 라멘안국"))
    db_session.execute(Place.__table__.update().where(Place.source_id == "K1").values(kakao_place_id="kakao:777"))
    db_session.flush()
    kakao.results = [_kakao("kakao:777", "오레노라멘 인사점", lat=37.5805, lng=126.9850), _kakao("kakao:8", "딴 곳")]   # 500m 가까이 떨어져 있다
    out = _search(db_session)
    assert [r.place_id for r in out] == [_pid(db_session, "K1"), "kakao:8"]
    assert not any("kakao_place_id" in r.model_dump() for r in out)
