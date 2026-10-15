"""POST /places/from-link (#474) — 링크 읽기, 단축 링크 SSRF 방어, 자체 DB 짝 찾기, 라우트. DB·네트워크 없이 돈다."""

from urllib.parse import quote

import httpx
import pytest

from common.errors import AppError
from places import api as places_api
from places import linkfetch, linkparse, matching
from places.matching import Candidate
from places.ratelimit import SlidingWindowLimiter

PUBLIC = lambda host, port: "142.250.196.110"  # noqa: E731 — 해석기 대역(공인 IP)

GOOGLE_PLACE = (
    f"https://www.google.com/maps/place/{quote('성수 칼국수')}/@37.5440,127.0560,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x1!8m2!3d37.5445!4d127.0561"
)


def code_of(call, *args):
    with pytest.raises(AppError) as exc:
        call(*args)
    return exc.value.code


# ---------------------------------------------------------------- 링크 읽기

def test_google_place_link_gives_name_and_the_place_pin_coordinates():
    parsed = linkparse.parse_resolved(linkparse.split_url(GOOGLE_PLACE).geturl())
    assert (parsed.provider, parsed.name_hint) == ("google", "성수 칼국수")
    assert (parsed.lat, parsed.lng) == (37.5445, 127.0561)   # @ 뷰포트(37.5440)가 아니라 !3d!4d 장소 핀


def test_google_link_without_pin_coordinates_falls_back_to_the_viewport_and_plus_means_space():
    parsed = linkparse.parse_resolved("https://www.google.com/maps/place/Seongsu+Kalguksu/@37.5,127.05,17z")
    assert (parsed.name_hint, parsed.lat, parsed.lng) == ("Seongsu Kalguksu", 37.5, 127.05)


def test_google_query_link_gives_only_a_name():
    parsed = linkparse.parse_resolved(f"https://www.google.com/maps?q={quote('서울숲')}")
    assert (parsed.name_hint, parsed.lat) == ("서울숲", None)


@pytest.mark.parametrize("url", [
    "https://www.google.com/maps/@37.5,127.05,15z",            # 보고 있는 화면뿐
    "https://www.google.com/maps?q=37.5445,127.0561",           # 좌표뿐
    "https://www.google.com/maps/place/37.5445,127.0561",
])
def test_google_map_address_without_a_place_is_unresolved(url):
    assert code_of(linkparse.parse_resolved, url) == "LINK_UNRESOLVED"


def test_google_non_map_page_is_not_a_map_link():
    assert linkparse.parse_resolved("https://www.google.com/search?q=칼국수") is None


@pytest.mark.parametrize("url,expected", [
    ("https://place.map.kakao.com/1234567", "kakao:1234567"),
    ("http://place.map.kakao.com/m/1234567", "kakao:1234567"),
    ("https://map.kakao.com/?itemId=1234567", "kakao:1234567"),
    ("https://map.kakao.com/?q=x&itemId=77&map_type=TYPE_MAP", "kakao:77"),
])
def test_kakao_links_give_only_the_place_id(url, expected):
    parsed = linkparse.parse_resolved(url)
    assert parsed == linkparse.ParsedLink("kakao", kakao_place_id=expected)


def test_kakao_map_address_without_id_is_unresolved():
    assert code_of(linkparse.parse_resolved, "https://map.kakao.com/link/map/성수,37.5,127.0") == "LINK_UNRESOLVED"


@pytest.mark.parametrize("url", [
    "https://naver.me/abc", "https://map.naver.com/p/entry/place/1", "https://www.instagram.com/p/abc/",
    "https://blog.naver.com/x/1", "ftp://www.google.com/maps/place/a", "javascript:alert(1)", "www.google.com/maps",
    "https://google.com.evil.com/maps/place/a", "https://evilgoogle.com/maps/place/a",
    "https://www.google.com@evil.com/maps/place/a", "https://user:pw@www.google.com/maps/place/a",
    "https://www.google.com:8080/maps/place/a", "http://127.0.0.1/maps", "http://localhost/", "", "   ",
])
def test_unsupported_hosts_and_shapes_are_rejected(url):
    assert code_of(linkparse.split_url, url) == "LINK_NOT_SUPPORTED"


def test_overlong_url_is_rejected():
    assert code_of(linkparse.split_url, "https://www.google.com/maps/place/" + "a" * 2000) == "LINK_NOT_SUPPORTED"


# ---------------------------------------------------------------- 단축 링크 · SSRF 방어

def make_client(handler):
    seen: list[httpx.Request] = []

    def wrapped(request):
        seen.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped), follow_redirects=False), seen


def redirect(location, status=302):
    return httpx.Response(status, headers={"location": location})


def test_short_link_is_followed_to_the_final_address_with_the_checked_ip_pinned():
    client, seen = make_client(lambda r: redirect(GOOGLE_PLACE))
    assert linkfetch.follow_short_link("https://maps.app.goo.gl/abc", client=client, resolve=PUBLIC) == GOOGLE_PLACE
    [req] = seen   # 최종 주소는 가져오지 않는다
    assert req.url.host == "142.250.196.110" and req.headers["host"] == "maps.app.goo.gl"
    assert req.extensions["sni_hostname"] == "maps.app.goo.gl"


def test_chain_of_short_links_is_followed_and_each_hop_is_resolved():
    resolved = []

    def resolve(host, port):
        resolved.append(host)
        return "142.250.196.110"

    client, _ = make_client(lambda r: redirect("https://goo.gl/maps/xyz") if r.headers["host"] == "maps.app.goo.gl"
                            else redirect("https://place.map.kakao.com/1"))
    assert linkfetch.follow_short_link("https://maps.app.goo.gl/a", client=client, resolve=resolve) == "https://place.map.kakao.com/1"
    assert resolved == ["maps.app.goo.gl", "goo.gl"]


def test_relative_redirect_is_resolved_against_the_current_address():
    client, seen = make_client(lambda r: redirect("/next") if r.url.path == "/abc" else redirect(GOOGLE_PLACE))
    assert linkfetch.follow_short_link("https://goo.gl/abc", client=client, resolve=PUBLIC) == GOOGLE_PLACE
    assert [r.url.path for r in seen] == ["/abc", "/next"] and seen[1].headers["host"] == "goo.gl"


def test_a_full_map_address_is_not_fetched():
    client, seen = make_client(lambda r: httpx.Response(500))
    assert linkfetch.follow_short_link(GOOGLE_PLACE, client=client, resolve=PUBLIC) == GOOGLE_PLACE
    assert seen == []


@pytest.mark.parametrize("target", [
    "http://169.254.169.254/latest/meta-data", "http://127.0.0.1/", "http://localhost/", "https://evil.example.com/x",
    "https://www.google.com.evil.com/maps", "file:///etc/passwd", "https://www.google.com:8443/maps", "gopher://www.google.com/",
])
def test_redirect_out_of_the_allowlist_stops(target):
    client, seen = make_client(lambda r: redirect(target))
    with pytest.raises(linkfetch.LinkFetchError):
        linkfetch.follow_short_link("https://maps.app.goo.gl/abc", client=client, resolve=PUBLIC)
    assert len(seen) == 1   # 허용 밖 주소로는 요청을 보내지 않는다


def test_a_short_host_that_resolves_to_a_private_ip_is_never_contacted():
    def resolve(host, port):
        raise linkfetch.LinkFetchError("공인 IP가 아닌 주소")

    client, seen = make_client(lambda r: httpx.Response(200))
    with pytest.raises(linkfetch.LinkFetchError):
        linkfetch.follow_short_link("https://maps.app.goo.gl/abc", client=client, resolve=resolve)
    assert seen == []


def test_redirect_count_is_limited():
    client, seen = make_client(lambda r: redirect("https://goo.gl/loop"))
    with pytest.raises(linkfetch.LinkFetchError, match="너무 많다"):
        linkfetch.follow_short_link("https://goo.gl/loop", client=client, resolve=PUBLIC)
    assert len(seen) == linkfetch.MAX_REDIRECTS + 1


@pytest.mark.parametrize("response", [httpx.Response(200, text="<html>"), httpx.Response(302), httpx.Response(404),
                                      redirect("https://www.google.com/" + "a" * 2100)])
def test_a_short_link_that_does_not_redirect_properly_fails(response):
    client, _ = make_client(lambda r: response)
    with pytest.raises(linkfetch.LinkFetchError):
        linkfetch.follow_short_link("https://kko.to/abc", client=client, resolve=PUBLIC)


def test_network_failure_and_timeout_become_fetch_errors():
    def boom(request):
        raise httpx.ConnectTimeout("t")

    client, _ = make_client(boom)
    with pytest.raises(linkfetch.LinkFetchError):
        linkfetch.follow_short_link("https://kko.to/abc", client=client, resolve=PUBLIC)


def test_client_ignores_environment_proxies_and_does_not_follow_redirects():
    client = linkfetch.make_client()
    assert client.follow_redirects is False and client.timeout.read == linkfetch.TIMEOUT_S


@pytest.mark.parametrize("ip,public", [
    ("142.250.196.110", True), ("2607:f8b0:4004:c07::71", True),
    ("10.0.0.1", False), ("172.16.5.5", False), ("192.168.0.1", False), ("127.0.0.1", False), ("169.254.169.254", False),
    ("100.64.0.1", False), ("0.0.0.0", False), ("::1", False), ("fe80::1", False), ("fc00::1", False),
    ("::ffff:10.0.0.1", False), ("::ffff:127.0.0.1", False), ("224.0.0.1", False), ("not-an-ip", False),
])
def test_only_public_ips_pass(ip, public):
    assert linkfetch.is_public_ip(ip) is public


def test_dns_answers_must_all_be_public(monkeypatch):
    import socket

    def answers(*ips):
        return lambda host, port, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    monkeypatch.setattr(socket, "getaddrinfo", answers("142.250.196.110", "142.250.196.111"))
    assert linkfetch.resolve_public_ip("goo.gl", 443) == "142.250.196.110"
    monkeypatch.setattr(socket, "getaddrinfo", answers("142.250.196.110", "10.0.0.5"))   # 하나라도 사설이면 막는다
    with pytest.raises(linkfetch.LinkFetchError):
        linkfetch.resolve_public_ip("goo.gl", 443)

    def fail(*a, **kw):
        raise socket.gaierror("no")

    monkeypatch.setattr(socket, "getaddrinfo", fail)
    with pytest.raises(linkfetch.LinkFetchError):
        linkfetch.resolve_public_ip("goo.gl", 443)


# ---------------------------------------------------------------- 자체 DB 짝 찾기

def cand(pid, name, dist=10.0, category="음식점", kakao=None):
    return Candidate(pid, name, 37.5445, 127.0561, category, kakao, dist, "서울 성동구 성수동 1")


@pytest.fixture()
def own(monkeypatch):
    """places.api의 자체 DB 조회 두 개를 대역으로 — 호출 인자를 남긴다."""
    state = {"near": [], "by_kakao": [], "calls": []}

    def near(lat, lng, radius_m, limit, *, db=None):
        state["calls"].append((lat, lng, radius_m, limit))
        return state["near"]

    monkeypatch.setattr(places_api, "own_places_near", near)
    monkeypatch.setattr(places_api, "own_places_by_kakao_id", lambda kid, *, db=None: state["by_kakao"])
    return state


def test_google_link_matches_own_db_places_within_100m_closest_first_at_most_five(own):
    own["near"] = [cand(f"p{i}", "성수 칼국수", dist=50 - i) for i in range(7)] + [cand("x", "전혀 다른 가게", dist=1)]
    result = places_api.parse_link(GOOGLE_PLACE)
    assert result.provider == "google" and result.name_hint == "성수 칼국수" and result.needs_search_query is False
    assert [m.place_id for m in result.matches] == [f"own:p{i}" for i in (6, 5, 4, 3, 2)]
    assert own["calls"] == [(37.5445, 127.0561, 100.0, matching.MAX_CANDIDATES)]
    assert all(m.pinnable is True for m in result.matches)


def test_google_match_uses_own_db_values_and_a_recorded_kakao_id_as_place_id(own):
    own["near"] = [cand("p1", "성수 칼국수", kakao="kakao:111")]
    [m] = places_api.parse_link(GOOGLE_PLACE).matches
    assert (m.place_id, m.place_name, m.category, m.address) == ("kakao:111", "성수 칼국수", "음식점", "서울 성동구 성수동 1")
    assert m.place_source is None   # 카카오 응답이 아니다


def test_google_link_without_a_matching_name_gives_no_matches_but_keeps_the_hint(own):
    own["near"] = [cand("x", "전혀 다른 가게")]
    result = places_api.parse_link(GOOGLE_PLACE)
    assert result.matches == [] and result.name_hint == "성수 칼국수" and result.needs_search_query is False


def test_google_link_without_coordinates_skips_the_db(own):
    result = places_api.parse_link(f"https://www.google.com/maps?q={quote('서울숲')}")
    assert result.matches == [] and result.name_hint == "서울숲" and own["calls"] == []


def test_kakao_link_with_an_own_db_match(own):
    own["by_kakao"] = [cand("p1", "성수 칼국수", kakao="kakao:1234567")]
    result = places_api.parse_link("https://place.map.kakao.com/1234567")
    assert (result.provider, result.kakao_place_id, result.name_hint, result.needs_search_query) == ("kakao", "kakao:1234567", None, False)
    assert [m.place_id for m in result.matches] == ["kakao:1234567"]


def test_kakao_link_without_a_match_asks_for_a_search_query(own):
    result = places_api.parse_link("https://place.map.kakao.com/1234567")
    assert result.matches == [] and result.needs_search_query is True and result.kakao_place_id == "kakao:1234567"
    assert result.model_dump(exclude_none=True).keys() == {"provider", "kakao_place_id", "matches", "needs_search_query"}


def test_short_link_is_resolved_then_read(own, monkeypatch):
    monkeypatch.setattr(linkfetch, "follow_short_link", lambda url, *, client, resolve=None: "https://place.map.kakao.com/42")
    assert places_api.parse_link("https://kko.to/abc").kakao_place_id == "kakao:42"


def test_short_link_that_cannot_be_opened_is_unresolved(own, monkeypatch):
    def fail(url, *, client, resolve=None):
        raise linkfetch.LinkFetchError("x")

    monkeypatch.setattr(linkfetch, "follow_short_link", fail)
    assert code_of(places_api.parse_link, "https://maps.app.goo.gl/abc") == "LINK_UNRESOLVED"


def test_short_link_that_resolves_to_a_non_place_page_is_unresolved(own, monkeypatch):
    monkeypatch.setattr(linkfetch, "follow_short_link", lambda url, *, client, resolve=None: "https://www.google.com/search?q=a")
    assert code_of(places_api.parse_link, "https://goo.gl/abc") == "LINK_UNRESOLVED"


def test_a_direct_non_map_address_is_not_supported(own):
    assert code_of(places_api.parse_link, "https://www.google.com/search?q=a") == "LINK_NOT_SUPPORTED"
    assert code_of(places_api.parse_link, "https://www.instagram.com/p/abc") == "LINK_NOT_SUPPORTED"


def test_nothing_from_the_link_reaches_the_logs(own, caplog):
    own["near"] = [cand("p1", "성수 칼국수")]
    with caplog.at_level("DEBUG"):
        places_api.parse_link(GOOGLE_PLACE)
        places_api.parse_link("https://place.map.kakao.com/1234567")
    text = caplog.text
    for secret in ("성수", "칼국수", "37.54", "127.05", "1234567", "google.com", "kakao.com"):
        assert secret not in text


# ---------------------------------------------------------------- 라우트

@pytest.fixture()
def client(own, monkeypatch):
    from fastapi.testclient import TestClient

    from auth.deps import get_current_user
    from auth.schemas import CurrentUser
    from common.database import get_db_session
    from main import app

    app.dependency_overrides[get_current_user] = lambda: CurrentUser(user_id="u1")
    app.dependency_overrides[get_db_session] = lambda: None
    monkeypatch.setattr(places_api, "link_limiter", SlidingWindowLimiter(2))
    yield TestClient(app)
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(get_db_session, None)


def test_route_returns_the_spec_shape(client, own):
    own["near"] = [cand("p1", "성수 칼국수")]
    r = client.post("/places/from-link", json={"url": GOOGLE_PLACE})
    assert r.status_code == 200
    assert r.json() == {
        "provider": "google", "name_hint": "성수 칼국수", "needs_search_query": False,
        "matches": [{"place_id": "own:p1", "place_name": "성수 칼국수", "lat": 37.5445, "lng": 127.0561,
                     "category": "음식점", "address": "서울 성동구 성수동 1", "pinnable": True}],
    }
    assert "37.5440" not in r.text   # 링크 안의 좌표를 싣지 않는다(자체 DB 장소의 좌표뿐)


def test_route_error_codes(client):
    assert client.post("/places/from-link", json={"url": "https://naver.me/abc"}).json()["code"] == "LINK_NOT_SUPPORTED"
    assert client.post("/places/from-link", json={"url": ""}).status_code == 422
    assert client.post("/places/from-link", json={"url": "x" * 2001}).status_code == 422
    assert client.post("/places/from-link", json={"url": "https://place.map.kakao.com/1", "extra": 1}).status_code == 422


def test_route_rate_limit_is_429(client):
    body = {"url": "https://place.map.kakao.com/1"}
    assert [client.post("/places/from-link", json=body).status_code for _ in range(3)] == [200, 200, 429]
