"""#1157 — 장소 블로그 사진: 검색어(상호명과 구, 도로명), 고르는 규칙, 얼굴 거르기, 저장하거나 캐시하지 않음. 카카오는 부르지 않는다."""

import httpx
import numpy as np
import pytest

from common.errors import AppError
from places import api, photos
from places.http import CallStats, SourceError, SourceHttp
from places.schemas import PlaceInfo


def _doc(n, *, host="postfiles.pstatic.net", w=900, h=700, **over):
    d = {
        "thumbnail_url": f"https://search1.kakaocdn.net/thumb/{n}",
        "doc_url": f"https://blog.naver.com/a/{n}",
        "image_url": f"https://{host}/img/{n}.jpg",
        "display_sitename": "네이버블로그",
        "width": w,
        "height": h,
    }
    d.update(over)
    return d


# ---- 검색어 ----

@pytest.mark.parametrize(("name", "address", "query"), [
    # 괄호(지점명, 법정동)와 쉼표 뒤(건물, 층)를 떼고 맨 앞 시나 도를 뺀다
    ("이디야(아현역점)", "서울특별시 서대문구 신촌로37길 10, 아현 메디컬 101호 일부 (북아현동)", "이디야 서대문구 신촌로37길 10"),
    ("청진동해장국", "서울특별시 구로구 구로중앙로 5 (구로동,(구로큰길 178))", "청진동해장국 구로구 구로중앙로 5"),
    ("한라 국수", "제주특별자치도 제주시 중앙로 25", "한라 국수 제주시 중앙로 25"),
    ("서라방", "종로구 서순라길 121 1층", "서라방 종로구 서순라길 121 1층"),   # 시나 도가 없으면 그대로
])
def test_query_is_name_plus_district_and_street(name, address, query):
    assert photos.photo_query(name, address) == query


@pytest.mark.parametrize(("name", "address"), [
    ("누룩목", None),               # 상호명만으로는 다른 지점 사진이 섞인다
    ("누룩목", "  "),
    (None, "서울특별시 서초구 강남대로43길 11"),
    ("(본점)", "서울특별시 서초구 강남대로43길 11"),
    ("누룩목", "서울특별시"),
])
def test_no_query_without_name_or_street(name, address):
    assert photos.photo_query(name, address) is None


# ---- 고르기 ----

def test_pick_skips_stickers_map_captures_link_previews_and_small_images():
    docs = [
        _doc(1, host="storep-phinf.pstatic.net"),    # 네이버 블로그 이모티콘
        _doc(2, host="simg.pstatic.net"),            # 글에 붙인 지도 캡처
        _doc(3, host="dthumb-phinf.pstatic.net"),    # 링크 미리보기
        _doc(4, w=120, h=120),                       # 작은 아이콘
        _doc(5, w=1200, h=299),                      # 짧은 변이 300 미만
        _doc(6),
        _doc(7, doc_url=None),                       # 원문 주소가 없으면 출처로 보낼 수 없다
        _doc(8),
        _doc(9),
        _doc(10),
    ]
    picked = photos.pick(docs)
    assert [p.thumbnail_url for p in picked] == [f"https://search1.kakaocdn.net/thumb/{n}" for n in (6, 8, 9)]
    assert picked[0] == photos.PlacePhoto(
        thumbnail_url="https://search1.kakaocdn.net/thumb/6", link_url="https://blog.naver.com/a/6", site_name="네이버블로그")


def test_pick_keeps_missing_site_name_as_empty_and_handles_missing_size():
    assert photos.pick([_doc(1, display_sitename=None)])[0].site_name == ""
    assert photos.pick([_doc(1, width=None, height=None)]) == []


# ---- place_photos ----

class _FakeSearch:
    def __init__(self, docs=None, *, configured=True, fail=False):
        self.docs, self.configured, self.fail, self.queries, self.fetched = docs or [], configured, fail, [], []

    def fetch_thumbnail(self, url):
        self.fetched.append(url)
        return b"img:" + url.encode()

    def is_configured(self):
        return self.configured

    def search(self, query):
        self.queries.append(query)
        if self.fail:
            raise SourceError("kakao_image image: HTTP 500")
        return self.docs


class _NoFaces:
    def has_face(self, data):
        return False


@pytest.fixture()
def real_mode(monkeypatch):
    monkeypatch.setattr(api, "_is_dev", lambda: False)
    monkeypatch.setattr(api, "_face_detector", lambda: _NoFaces())
    place = PlaceInfo(place_id="p1", name="누룩목", lat=37.5, lng=127.0, category="음식점", address="서울특별시 서초구 강남대로43길 11, 소망빌딩 1층 (서초동)")
    monkeypatch.setattr(api, "get_places", lambda ids, db=None: {"p1": place} if "p1" in ids else {})

    def install(search):
        monkeypatch.setattr(api, "_image_search", lambda: search)
        return search

    return install


def test_place_photos_searches_name_and_address_and_picks(real_mode):
    search = real_mode(_FakeSearch([_doc(1, host="storep-phinf.pstatic.net"), _doc(2), _doc(3)]))
    got = api.place_photos("p1")
    assert search.queries == ["누룩목 서초구 강남대로43길 11"]
    assert [p.link_url for p in got] == ["https://blog.naver.com/a/2", "https://blog.naver.com/a/3"]


def test_place_photos_is_not_cached_each_open_calls_again(real_mode):
    """카카오 응답은 메모리에도 남기지 않는다(#53과 같은 규칙) — 같은 장소를 두 번 열면 두 번 부른다."""
    search = real_mode(_FakeSearch([_doc(1)]))
    api.place_photos("p1")
    api.place_photos("p1")
    assert len(search.queries) == 2


def test_place_photos_unknown_place_returns_empty_without_calling(real_mode):
    search = real_mode(_FakeSearch([_doc(1)]))
    assert api.place_photos("nope") == []
    assert search.queries == []


def test_place_photos_dev_mode_never_calls_kakao(monkeypatch):
    monkeypatch.setattr(api, "_is_dev", lambda: True)
    search = _FakeSearch([_doc(1)])
    monkeypatch.setattr(api, "_image_search", lambda: search)
    assert api.place_photos("p1") == []
    assert search.queries == []


@pytest.mark.parametrize("search", [_FakeSearch(configured=False), _FakeSearch(fail=True)])
def test_place_photos_without_key_or_on_failure_is_places_unavailable(real_mode, search):
    real_mode(search)
    with pytest.raises(AppError) as err:
        api.place_photos("p1")
    assert err.value.code == "PLACES_UNAVAILABLE"


# ---- 얼굴 거르기 ----

def _photo(n):
    return photos.PlacePhoto(thumbnail_url=f"https://search1.kakaocdn.net/t/{n}", link_url=f"https://blog.naver.com/a/{n}", site_name="네이버블로그")


def test_without_faces_skips_faces_unreadable_and_unfetched_and_stops_at_limit():
    """1: 받지 못함, 2: 얼굴, 3: 읽지 못함, 4·5·6: 얼굴 없음, 7: 3장을 채워 받지 않는다."""
    fetched = []

    def fetch(url):
        fetched.append(url)
        return None if url.endswith("/1") else url.encode()

    def has_face(data):
        n = int(data.decode().rsplit("/", 1)[1])
        return {2: True, 3: None}.get(n, False)

    got = photos.without_faces([_photo(n) for n in range(1, 8)], fetch, has_face)
    assert [p.link_url.rsplit("/", 1)[1] for p in got] == ["4", "5", "6"]
    assert "https://search1.kakaocdn.net/t/7" not in fetched


def test_place_photos_drops_photos_with_faces(real_mode, monkeypatch):
    real_mode(_FakeSearch([_doc(1), _doc(2), _doc(3), _doc(4)]))

    class SelfieIsTwo:
        def has_face(self, data):
            return data.endswith(b"/2")

    monkeypatch.setattr(api, "_face_detector", lambda: SelfieIsTwo())
    assert [p.link_url for p in api.place_photos("p1")] == [f"https://blog.naver.com/a/{n}" for n in (1, 3, 4)]


@pytest.mark.parametrize("url", [
    "http://search1.kakaocdn.net/t/1",            # https 가 아님
    "https://example.com/t/1",                    # 카카오 CDN 이 아님
    "https://kakaocdn.net.evil.com/t/1",          # 이름만 비슷한 주소
    "https://evilkakaocdn.net/t/1",
])
def test_fetch_thumbnail_only_kakao_cdn_https(url):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, content=b"x")

    search = photos.KakaoImageSearch(SourceHttp(httpx.Client(transport=httpx.MockTransport(handler)), CallStats(), retries=0), "key")
    assert search.fetch_thumbnail(url) is None
    assert calls == []


def test_fetch_thumbnail_gets_bytes_and_gives_up_over_limit(monkeypatch):
    def handler(request):
        size = 10 if request.url.path.endswith("/small") else photos.THUMBNAIL_MAX_BYTES + 1
        return httpx.Response(200, content=b"x" * size)

    search = photos.KakaoImageSearch(SourceHttp(httpx.Client(transport=httpx.MockTransport(handler)), CallStats(), retries=0), "key")
    assert search.fetch_thumbnail("https://search1.kakaocdn.net/small") == b"x" * 10
    assert search.fetch_thumbnail("https://search1.kakaocdn.net/big") is None


def test_real_detector_loads_model_and_reads_plain_image_as_no_face():
    """모델 파일이 이미지에 들어 있고 opencv 가 읽는지 본다. 빈 그림은 얼굴 없음, 깨진 데이터는 읽지 못함(None)."""
    import cv2

    assert photos.FACE_MODEL.exists()
    detector = photos.FaceDetector()
    ok, png = cv2.imencode(".png", np.full((130, 130, 3), 200, np.uint8))
    assert ok
    assert detector.has_face(png.tobytes()) is False
    assert detector.has_face(b"not an image") is None

