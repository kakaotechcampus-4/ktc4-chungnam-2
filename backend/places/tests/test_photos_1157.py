"""#1157 — 장소 블로그 사진: 검색어(상호명과 구, 도로명), 고르는 규칙, 저장하거나 캐시하지 않음. 카카오는 부르지 않는다."""

import pytest

from common.errors import AppError
from places import api, photos
from places.http import SourceError
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
        self.docs, self.configured, self.fail, self.queries = docs or [], configured, fail, []

    def is_configured(self):
        return self.configured

    def search(self, query):
        self.queries.append(query)
        if self.fail:
            raise SourceError("kakao_image image: HTTP 500")
        return self.docs


@pytest.fixture()
def real_mode(monkeypatch):
    monkeypatch.setattr(api, "_is_dev", lambda: False)
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
