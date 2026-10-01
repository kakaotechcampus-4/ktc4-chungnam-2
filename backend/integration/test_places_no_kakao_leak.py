"""카카오(지도 API) 응답이 메모리·DB·LLM 어디에도 남거나 넘어가지 않는다 (#188, #53 결정).

실제 recommend 실행 경로를 real 게이트웨이로 돌리되 지도 소스만 대역(카카오 표식 값을 담은)으로 바꾼다.
- LLM: recommend가 llm.label_place에 넘기는 원자료 인자를 가로채 표식이 없고 비어 있는지 본다.
- DB: 실행 뒤 후보 행 어디에도 표식이 없다(place_id·좌표만 저장 대상).
- 메모리: PlaceService에는 소스 목록 말고 어떤 상태도 없다.
"""

import json

import pytest

from main import app  # noqa: F401
from places import api as places_api
from places.service import PlaceService
from places.tests.test_fallback import place
from places.tests.test_name_search import NamedFake
from recommend import flows, service
from recommend.deps import RealPlaceFactsGateway, RealPlaceSearchGateway
from recommend.tests.test_flows import _make_members, _make_region, _make_run

MARK = dict(name="카카오전용가게ZZ", phone="02-000-KAKAO", address="카카오주소ZZ", place_url="http://kakao.example/zz")
MARKERS = ("카카오전용가게ZZ", "02-000-KAKAO", "카카오주소ZZ", "kakao.example/zz")


class _KakaoWithMarkers(NamedFake):
    """카카오 어댑터 대역 — 근처 검색과 이름 검색 둘 다 표식이 든 장소를 돌려준다."""

    def __init__(self):
        super().__init__("kakao", result=[place(**MARK)])
        self._nearby = [place(source_id="1", lat=35.0005, lng=129.0005, **MARK)]


@pytest.fixture()
def wired(monkeypatch):
    svc = PlaceService([_KakaoWithMarkers()])
    monkeypatch.setattr(places_api, "_is_dev", lambda: False)
    monkeypatch.setattr(places_api, "_service", lambda: svc)
    return svc


def test_kakao_values_never_reach_llm_or_db_through_a_recommend_run(db_session, wired, monkeypatch):
    seen_by_llm: list[tuple] = []
    real_label = flows.llm_service.label_place

    def spy(raw_facts, *args, **kwargs):
        seen_by_llm.append((dict(raw_facts), args, kwargs))
        return real_label(raw_facts, *args, **kwargs)

    monkeypatch.setattr(flows.llm_service, "label_place", spy)

    run = _make_run(db_session, status="collecting_evidence")
    _make_members(db_session, user_ids=["user_1"])
    _make_region(db_session, run, center_lat=35.0, center_lng=129.0, radius_m=1000)

    flows.execute_run(db_session, run_id=str(run.id),
                      place_search=RealPlaceSearchGateway(), place_facts=RealPlaceFactsGateway())

    assert seen_by_llm, "검색 결과가 풀에 들어가 라벨링 호출이 있어야 이 테스트가 의미가 있다"
    for raw_facts, args, kwargs in seen_by_llm:
        assert raw_facts == {}                                    # 카카오 원자료가 LLM 인자로 가지 않는다
        dumped = json.dumps([raw_facts, args, kwargs], ensure_ascii=False, default=str)
        assert not any(m in dumped for m in MARKERS)

    candidates = service.list_candidates(db_session, str(run.id))
    assert [c.place_id for c in candidates] == ["kakao:1"]        # 식별자와 좌표만 남는다
    row_dump = json.dumps([{k: v for k, v in vars(c).items() if not k.startswith("_")} for c in candidates],
                          ensure_ascii=False, default=str)
    assert not any(m in row_dump for m in MARKERS)


def test_raw_facts_gateway_is_empty_right_after_search_and_name_search(wired):
    RealPlaceSearchGateway().search_nearby(category="음식점", circles=[])   # 호출 자체는 가능
    wired.search_by_name("가게", None, 5)
    wired.search_nearby("음식점", [])
    assert RealPlaceFactsGateway().get_raw_facts("kakao:1") == {}
    assert set(vars(wired)) == {"_sources"}                        # 메모리에도 응답을 쥐고 있지 않다


def test_name_search_response_is_display_only_and_pin_creation_needs_echo(app_client, two_users, wired):
    """GET /places/search는 응답으로만 값을 돌려준다. 이어지는 핀 생성은 서버 기억이 아니라 echo 값에 의존한다."""
    from fastapi.testclient import TestClient

    c = TestClient(app_client.app, cookies={"session": "user_a"})
    r = c.get("/places/search", params={"q": "카카오"})
    assert r.status_code == 200 and r.json()[0]["place_name"] == "카카오전용가게ZZ"
    m = c.post("/maps", json={"title": "t", "start_date": "2026-11-01", "end_date": "2026-11-02",
                              "region": {"label": "부산", "lat": 35.0, "lng": 129.0}}).json()["id"]
    # 좌표를 빼면(서버가 기억하고 있다면 채워졌을 것) 거절된다 — real 모드가 아니라 dev 게이트웨이라도 422다
    r2 = c.post(f"/maps/{m}/pins", json={"category": "음식점", "source": "search", "place_id": "kakao:1",
                                          "place_name": "카카오전용가게ZZ"})
    assert r2.status_code == 422
