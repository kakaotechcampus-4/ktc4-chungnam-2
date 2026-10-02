"""
카카오 응답 비저장(#53) 종단 검증 — 검색 → 핀 만들기 → 반응 → run → 실행 → 게시를 실제 장소 DB 위에서 HTTP로 돌린 뒤,
**모든 테이블의 모든 행**과 로그, ②(모델) 입력에 카카오가 준 값이 남아 있지 않은지 본다.

카카오 대역은 실제 가게와 같은 이름(그래야 자체 DB와 매칭된다)에, 자체 DB에는 없는 표식 값(전화·주소·정밀 좌표)을 싣는다.
허용되는 카카오 유래 값은 `places.kakao_place_id/kakao_place_url/kakao_matched_at`뿐이다.
"""

import json
import logging

import pytest
from sqlalchemy import text

from common.database import Base
from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _pin, fake_planner, members, own_db, place_ids, real_client,
)
from places import api as places_api
from places.service import PlaceService
from places.tests.test_fallback import place
from places.tests.test_name_search import NamedFake

# 카카오가 준 값 — 자체 DB(인허가 데이터)에는 없다
KAKAO = dict(
    source_id="MARKKID", name=PLACES["K"][0], phone="02-000-KAKAO", address="카카오주소ZZ",
    lat=37.54471234, lng=127.05631234, place_url="http://kakao.example/zz",
)
MARKERS = ("02-000-KAKAO", "카카오주소ZZ", "37.54471234", "127.05631234", "kakao.example/zz")


class _KakaoMarker(NamedFake):
    def __init__(self):
        super().__init__("kakao", result=[place(**KAKAO)])


@pytest.fixture()
def kakao_wired(monkeypatch):
    svc = PlaceService([_KakaoMarker()])
    monkeypatch.setattr(places_api, "_is_dev", lambda: False)
    monkeypatch.setattr(places_api, "_service", lambda: svc)
    monkeypatch.setattr(places_api, "search_limiter", places_api.SlidingWindowLimiter(1000))


def _all_rows_text(db_session) -> dict[str, list[str]]:
    out = {}
    for table in Base.metadata.sorted_tables:
        out[table.name] = list(db_session.execute(text(f'SELECT t::text FROM "{table.name}" t')).scalars())
    return out


def test_no_kakao_value_is_stored_logged_or_sent_to_the_model(members, place_ids, kakao_wired, monkeypatch, caplog, db_session):
    import llm.service as llm_service

    a, b, map_id = members
    sent_to_model: list[str] = []
    inner = llm_service.get_evidence_planner()

    def spying_planner(raw_reasons):
        sent_to_model.append(json.dumps(list(raw_reasons), ensure_ascii=False, default=str))
        return inner(raw_reasons)

    monkeypatch.setattr(llm_service, "get_evidence_planner", lambda: spying_planner)
    caplog.set_level(logging.DEBUG)

    # 1) 검색 — 화면 표시용이라 응답에는 카카오 값이 있어도 된다(저장만 안 된다)
    found = a.get("/places/search", params={"q": "성수 한식집", "lat": 37.5445, "lng": 127.0561})
    assert found.status_code == 200, found.text
    [hit] = found.json()
    assert hit["lat"] == 37.54471234, "대조군 — 카카오 대역의 값이 검색 응답에는 나온다"

    # 2) 결과를 그대로 되돌려 핀을 만든다 — 핀의 이름·좌표는 자체 DB 장소의 것이어야 한다
    pin = a.post(f"/maps/{map_id}/pins", json={
        "category": hit["category"], "source": "search", "place_id": hit["place_id"],
        "place_name": hit["place_name"], "lat": hit["lat"], "lng": hit["lng"]})
    assert pin.status_code == 201, pin.text
    assert pin.json()["place_name"] == PLACES["K"][0]
    assert abs(pin.json()["lat"] - PLACES["K"][1]) < 1e-6 and abs(pin.json()["lng"] - PLACES["K"][2]) < 1e-6, (
        "핀 좌표는 카카오 힌트가 아니라 자체 DB 좌표여야 한다"
    )
    _pin(a, map_id, "S", place_ids)

    # 3) 반응 → run → 실행 → 게시
    assert a.put(f"/pins/{pin.json()['id']}/reaction", json={"type": "against", "reason_text": "한식 말고 다른 거"}).status_code == 200
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    candidates = a.get(f"/runs/{run_id}/result").json()["candidates"]
    assert candidates
    assert a.post(f"/candidates/{candidates[0]['id']}/publish").status_code == 200

    # 4) 어디에도 카카오 값이 없다
    rows = _all_rows_text(db_session)
    leaks = [(table, marker) for table, texts in rows.items() for marker in MARKERS if any(marker in row for row in texts)]
    assert not leaks, f"카카오가 준 값이 DB에 남았다: {leaks}"
    assert not any(marker in caplog.text for marker in MARKERS), "카카오가 준 값이 로그에 남았다"
    assert not any(marker in payload for marker in MARKERS for payload in sent_to_model), "카카오 값이 모델(②)로 갔다"
    assert sent_to_model, "대조군 — ②가 실제로 불렸다(검사가 공허하지 않다)"

    # 5) 허용된 것만: places.kakao_place_id/url/matched_at
    kakao_rows = [row for row in rows["places"] if "MARKKID" in row]
    assert kakao_rows, "매칭된 자체 DB 장소에 카카오 장소 ID가 기록된다(허용)"
    others = [(t, r) for t, texts in rows.items() if t != "places" for r in texts if "MARKKID" in r and t != "event_log"]
    assert not others, f"카카오 장소 ID가 places 밖에 저장됐다: {[t for t, _ in others]}"


def test_control_the_scan_detects_a_planted_leak(own_db):
    """대조군 — 표식 값을 일부러 한 행에 심으면 위 스캔이 그 테이블을 잡아낸다(위 통과가 공허하지 않다는 증거)."""
    own_db.execute(text("UPDATE places SET phone = :p WHERE source_id = 'K'"), {"p": KAKAO["phone"]})
    rows = _all_rows_text(own_db)
    hits = [t for t, texts in rows.items() if any(KAKAO["phone"] in r for r in texts)]
    assert hits == ["places"]
