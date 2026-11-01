"""네이버 링크 번호 읽기와 번호표(#1048) — 단축 링크 한 번 따라가기, 신뢰 규칙(hint 즉시·user 2표·충돌·폐업), 탈퇴 표 정리, 약관(번호만 저장)."""

import dataclasses
import logging

import httpx
import pytest
from sqlalchemy import func, inspect, select

import main  # noqa: F401 — 순환 import 방지
from common.errors import AppError
from places import api, core, linkfetch, linkparse
from places.models import Place, PlaceExternalId, PlaceExternalIdVote
from places.testing import FakePlaces

PUBLIC = lambda host, port: "223.130.200.104"  # noqa: E731 — 해석기 대역(공인 IP)
NID = "naver:1412566798"
MAP_URL = "https://map.naver.com/p/search/%EB%A7%9B%EC%A7%91?c=15.00,0,0,0,dh&pinId=1412566798&placePath=%2Fhome"


def code_of(call, *args):
    with pytest.raises(AppError) as exc:
        call(*args)
    return exc.value.code


# ---- 링크 읽기 ----

@pytest.mark.parametrize("url,eid", [
    (MAP_URL, NID),
    ("https://map.naver.com/p/entry/place/1412566798?c=1", NID),
    ("https://m.place.naver.com/restaurant/1412566798/home", NID),
    ("https://m.place.naver.com/place/77", "naver:77"),
])
def test_naver_number_is_read_and_nothing_else(url, eid):
    parsed = linkparse.parse_resolved(url)
    assert (parsed.provider, parsed.external_id) == ("naver", eid)
    assert (parsed.name_hint, parsed.lat, parsed.lng, parsed.kakao_place_id) == (None, None, None, None)


@pytest.mark.parametrize("url", [
    "https://map.naver.com/p/search/%EB%A7%9B%EC%A7%91", "https://map.naver.com/?pinId=abc", "https://m.place.naver.com/",
])
def test_naver_map_address_without_a_number_is_unresolved(url):
    assert code_of(linkparse.parse_resolved, url) == "LINK_UNRESOLVED"


@pytest.mark.parametrize("url", ["https://naver.me/FvTH6o34", "https://map.naver.com/x", "https://m.place.naver.com/restaurant/1"])
def test_three_naver_hosts_are_allowed(url):
    assert linkparse.split_url(url)


@pytest.mark.parametrize("url", ["https://blog.naver.com/x/1", "https://www.naver.com/", "https://naver.me.evil.com/a", "https://evilmap.naver.com.x.com/"])
def test_other_naver_hosts_are_rejected(url):
    assert code_of(linkparse.split_url, url) == "LINK_NOT_SUPPORTED"


def make_client(handler):
    seen = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped), follow_redirects=False), seen


def test_naver_me_is_followed_once_and_the_map_page_is_never_fetched():
    client, seen = make_client(lambda r: httpx.Response(307, headers={"location": MAP_URL}))
    assert linkfetch.follow_short_link("https://naver.me/FvTH6o34", client=client, resolve=PUBLIC) == MAP_URL
    [req] = seen   # map.naver.com 본문은 열지 않는다(Location 헤더만)
    assert req.headers["host"] == "naver.me"


def test_naver_me_redirecting_outside_the_allowlist_stops():
    client, seen = make_client(lambda r: httpx.Response(302, headers={"location": "http://169.254.169.254/x"}))
    with pytest.raises(linkfetch.LinkFetchError):
        linkfetch.follow_short_link("https://naver.me/abc", client=client, resolve=PUBLIC)
    assert len(seen) == 1


def test_parse_link_reads_a_naver_short_link_as_a_number_not_an_error(monkeypatch):
    monkeypatch.setattr(api.linkfetch, "follow_short_link", lambda url, *, client: MAP_URL)
    monkeypatch.setattr(api, "_link_client", lambda: None)
    monkeypatch.setattr(api, "own_places_by_external_id", lambda eid, *, db=None: [])
    r = api.parse_link("https://naver.me/FvTH6o34")
    assert (r.provider, r.external_id, r.matches, r.matched_by, r.needs_search_query) == ("naver", NID, [], None, True)


# ---- 신뢰 규칙(순수) ----

@pytest.mark.parametrize("rows,expected", [
    ([("p1", "hint", 0)], "p1"),
    ([("p1", "user", 2)], "p1"),
    ([("p1", "user", 1)], None),            # 사용자 1명 표만으로는 자동 매칭하지 않는다
    ([("p1", "user", 0)], None),
    ([("p1", "hint", 0), ("p2", "hint", 0)], None),   # 같은 번호가 다른 장소에 — 충돌
    ([("p1", "hint", 0), ("p2", "user", 5)], None),
    ([], None),
])
def test_trusted_external_place(rows, expected):
    assert core.trusted_external_place(rows) == expected


# ---- DB: 기록·조회 ----

def _place(db, sid, name="성수 칼국수", status="open", category="음식점"):
    p = Place(source="permit", source_id=sid, name=name, category=category, address="서울 성동구 성수이로 100", status=status,
              geom=func.ST_SetSRID(func.ST_MakePoint(127.05, 37.54), 4326))
    db.add(p)
    db.flush()
    return str(p.id)


def test_hint_record_is_trusted_at_once(db_session):
    pid = _place(db_session, "1")
    api.record_external_id("naver", NID, pid, source="hint", db=db_session)
    [c] = api.own_places_by_external_id(NID, db=db_session)
    assert c.place_id == pid


def test_user_record_needs_two_different_voters(db_session):
    pid = _place(db_session, "1")
    api.record_external_id("naver", NID, pid, source="user", voter_hash="h1", db=db_session)
    assert api.own_places_by_external_id(NID, db=db_session) == []
    api.record_external_id("naver", NID, pid, source="user", voter_hash="h1", db=db_session)   # 같은 사람은 한 표
    assert api.own_places_by_external_id(NID, db=db_session) == []
    api.record_external_id("naver", NID, pid, source="user", voter_hash="h2", db=db_session)
    assert [c.place_id for c in api.own_places_by_external_id(NID, db=db_session)] == [pid]


def test_hint_upgrades_a_user_row(db_session):
    pid = _place(db_session, "1")
    api.record_external_id("kakao", "kakao:9", pid, source="user", voter_hash="h1", db=db_session)
    assert api.own_places_by_external_id("kakao:9", db=db_session) == []
    api.record_external_id("kakao", "kakao:9", pid, source="hint", db=db_session)
    assert [c.place_id for c in api.own_places_by_external_id("kakao:9", db=db_session)] == [pid]


def test_conflict_removes_the_number_from_auto_matching(db_session):
    a, b = _place(db_session, "1"), _place(db_session, "2", name="다른 가게")
    api.record_external_id("naver", NID, a, source="hint", db=db_session)
    assert [c.place_id for c in api.own_places_by_external_id(NID, db=db_session)] == [a]
    api.record_external_id("naver", NID, b, source="hint", db=db_session)
    assert api.own_places_by_external_id(NID, db=db_session) == []


def test_closed_place_is_excluded(db_session):
    pid = _place(db_session, "1", status="closed")
    api.record_external_id("naver", NID, pid, source="hint", db=db_session)
    assert api.own_places_by_external_id(NID, db=db_session) == []


def test_unknown_number_and_bad_input(db_session):
    assert api.own_places_by_external_id("naver:1", db=db_session) == []
    assert api.own_places_by_external_id("garbage", db=db_session) == []
    pid = _place(db_session, "1")
    for args, kw in [(("tistory", "tistory:1", pid), {"source": "hint"}), (("naver", "kakao:1", pid), {"source": "hint"}),
                     (("naver", NID, pid), {"source": "user"}), (("naver", NID, pid), {"source": "other"})]:
        with pytest.raises(ValueError):
            api.record_external_id(*args, db=db_session, **kw)
    with pytest.raises(KeyError):
        api.record_external_id("naver", NID, "00000000-0000-0000-0000-000000000001", source="hint", db=db_session)


def test_parse_link_returns_matches_from_the_table_for_kakao_and_naver(db_session):
    pid = _place(db_session, "1")
    api.record_external_id("naver", NID, pid, source="hint", db=db_session)
    api.record_external_id("kakao", "kakao:909739262", pid, source="hint", db=db_session)
    r = api.parse_link(MAP_URL, db=db_session)
    assert (r.provider, r.external_id, r.matched_by, r.needs_search_query) == ("naver", NID, "external_id", False)
    assert [m.place_name for m in r.matches] == ["성수 칼국수"] and r.matches[0].pinnable
    r = api.parse_link("https://place.map.kakao.com/909739262", db=db_session)
    assert (r.provider, r.external_id, r.kakao_place_id, r.matched_by) == ("kakao", "kakao:909739262", "kakao:909739262", "external_id")
    assert [m.place_name for m in r.matches] == ["성수 칼국수"]
    r = api.parse_link("https://place.map.kakao.com/1", db=db_session)   # 번호표에 없다
    assert (r.matches, r.matched_by, r.needs_search_query, r.external_id) == ([], None, True, "kakao:1")


def test_hint_match_records_the_number_and_the_same_link_matches_next_time(db_session):
    pid = _place(db_session, "1")
    got = api.match_by_name_address("성수 칼국수", "서울 성동구 성수이로 100", external_id=NID, db=db_session)
    assert [r.place_name for r in got] == ["성수 칼국수"]
    assert [c.place_id for c in api.own_places_by_external_id(NID, db=db_session)] == [pid]
    assert api.match_by_name_address("없는 가게", "서울 성동구 성수이로 100", external_id="naver:5", db=db_session) == []
    assert api.own_places_by_external_id("naver:5", db=db_session) == []   # 짝이 없으면 기록하지 않는다
    assert api.match_by_name_address("성수 칼국수", "서울 성동구 성수이로 100", external_id="not-a-number", db=db_session)   # 형식이 틀리면 기록만 건너뛴다


def test_purge_removes_only_that_voters_votes_and_is_idempotent(db_session):
    pid = _place(db_session, "1")
    api.record_external_id("naver", NID, pid, source="user", voter_hash="h1", db=db_session)
    api.record_external_id("naver", NID, pid, source="user", voter_hash="h2", db=db_session)
    assert len(api.own_places_by_external_id(NID, db=db_session)) == 1
    assert api.purge_external_id_votes("h1", db=db_session) == 1
    assert api.own_places_by_external_id(NID, db=db_session) == []   # 한 표가 빠져 신뢰가 풀린다
    assert api.purge_external_id_votes("h1", db=db_session) == 0
    assert db_session.scalar(select(func.count()).select_from(PlaceExternalId)) == 1   # 번호표 행은 남는다
    assert db_session.scalar(select(func.count()).select_from(PlaceExternalIdVote)) == 1


def test_only_numbers_are_stored(db_session):
    """카카오 약관(#53): 번호표는 번호·장소 id·출처뿐이다 — 이름·좌표·주소 칸이 없다."""
    insp = inspect(db_session.get_bind())
    assert {c["name"] for c in insp.get_columns("place_external_ids")} == {"id", "provider", "external_id", "place_id", "source", "created_at"}
    assert {c["name"] for c in insp.get_columns("place_external_id_votes")} == {"external_id_row", "voter_hash", "created_at"}


def test_numbers_are_not_logged(db_session, caplog):
    pid = _place(db_session, "1")
    api.record_external_id("naver", NID, pid, source="hint", db=db_session)
    with caplog.at_level(logging.DEBUG):
        api.parse_link(MAP_URL, db=db_session)
    assert "1412566798" not in caplog.text


# ---- 메모리 대역 ----

def test_fake_external_ids_follow_the_same_rules():
    fake = FakePlaces()
    pid = fake.place_id("seongsu-kalguksu")
    fake.record_external_id("naver", NID, pid, source="user", voter_hash="a")
    assert fake.own_places_by_external_id(NID) == []
    fake.record_external_id("naver", NID, pid, source="user", voter_hash="b")
    assert [c.place_id for c in fake.own_places_by_external_id(NID)] == [pid]
    assert fake.purge_external_id_votes("a") == 1 and fake.own_places_by_external_id(NID) == []


# ---- voter_hash ----

def test_voter_hash_is_stable_one_way_and_per_user():
    a, b = api.voter_hash("user-1"), api.voter_hash("user-2")
    assert a == api.voter_hash("user-1") and a != b
    assert len(a) == 64 and int(a, 16) >= 0 and "user-1" not in a


def test_voter_hash_depends_on_the_secret(monkeypatch):
    before = api.voter_hash("user-1")
    monkeypatch.setattr(api, "settings", dataclasses.replace(api.settings, session_secret="another-secret"))
    assert api.voter_hash("user-1") != before


def test_voter_hash_and_secret_are_not_logged(caplog, monkeypatch):
    with caplog.at_level(logging.DEBUG):
        h = api.voter_hash("user-1")
    assert h not in caplog.text and api.settings.session_secret not in caplog.text
