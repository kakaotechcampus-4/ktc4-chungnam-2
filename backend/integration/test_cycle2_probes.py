"""
점검 루프 2회차 탐색 — ♥ 선호 프로필(D6), 검색 원(D10), 카카오 힌트 검증(D21), ②의 글자 에코 취약성(D25).

처음에는 올바른 동작을 그대로 단언하는 일반 테스트로 쓰고 돌려서, 실패한 것만 결함으로 확정한다.
"""

import unicodedata
from datetime import datetime, timezone

import pytest
from sqlalchemy import text, update

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, RUN_CENTER, _pin, fake_planner, members, own_db, place_ids, real_client,
)
from places import repository
from places.models import Place
from places.ingest import LabelRow, PlaceRow

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _extra_place(db, sid, name, lat, lng, facts):
    repository.upsert_places(db, [PlaceRow("permit", sid, name, "음식점", f"서울 {sid}", None, lat, lng, "open")])
    repository.upsert_facts(db, [LabelRow("permit", sid, k, v, "known", 3, NOW) for k, v in facts.items()])
    db.flush()
    db.execute(update(Place).where(Place.source_id == sid).values(curated=True))  # 추천 후보 풀에 들어가게(#558)
    db.flush()


def _run(a, map_id, center=None, monkeypatch=None):
    """center를 주면 run 생성 동안만 시·도 판정을 통과로 본다(테스트 DB에는 시·도 경계가 없다). 실행의 시·도 제한은 그대로다."""
    body = {"category": "음식점", "center": {"lat": center[0], "lng": center[1]} if center else RUN_CENTER}   # center는 필수(#1354)
    if monkeypatch is not None:
        from recommend import flows
        with monkeypatch.context() as patch:
            patch.setattr(flows.places_api, "sido_at", lambda *args, **kwargs: "sido")
            run_id = a.post(f"/maps/{map_id}/runs", json=body).json()["id"]
    else:
        run_id = a.post(f"/maps/{map_id}/runs", json=body).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    return run_id


# ───────────────────────── D6 — ♥ 선호 프로필 ─────────────────────────

def test_d6_hearted_places_shape_the_preference_profile(members, place_ids, fake_planner, db_session):
    """문서 "선호 점수 — 입력 1": ♥가 달린 장소들의 라벨 자체를 선호 신호로 쓴다. 둘이 횟집에 ♥ → 횟집 계열(raw_fish 참)이 위로."""
    a, b, map_id = members
    # 후보: 가까운 분식집 B(raw_fish 거짓) vs 조금 먼 횟집 R2(raw_fish 참) — 프로필이 죽어 있으면 가까운 B가 먼저다
    _extra_place(db_session, "R2", "성수 횟집2", 37.5465, 127.0540,
                 {"cuisine_korean": False, "cuisine_raw_fish": True, "spicy_focused": False})
    r_pin = _pin(a, map_id, "R", place_ids)
    assert a.put(f"/pins/{r_pin}/reaction", json={"type": "like"}).status_code == 200
    assert b.put(f"/pins/{r_pin}/reaction", json={"type": "like"}).status_code == 200
    run_id = _run(a, map_id)
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200, result.text
    names = [c["place_name"] for c in sorted(result.json()["candidates"], key=lambda c: c["rank"])]
    # 후보는 상위 3곳이다. 프로필이 살아 있으면 횟집2(raw_fish 참, ♥ 두 명 지지)가 거리와 상관없이 1위다.
    assert names and names[0] == "성수 횟집2", f"♥ 프로필이 점수에 반영되지 않았다(거리순으로만 정렬됨): {names}"


# ───────────────────────── D10 — 검색 원 ─────────────────────────

def test_d10_run_circle_is_the_map_center_not_the_pins_midpoint_1331(members, place_ids, fake_planner, db_session, monkeypatch):
    """#1331 — run의 검색 원은 지도 중심 한 점이다. 성수 핀 하나와 8km 떨어진 홍대 핀 하나가 있어도, 중심을 성수에 두면 성수 일대
    후보가 나온다(핀들의 중간 빈 땅이 중심이 되지 않는다). 핀마다 원을 그리던 옛 방식은 readiness·미리 돌려 보기(중심 없는 호출)에만 남았다."""
    a, b, map_id = members
    _extra_place(db_session, "H", "홍대 라멘집", 37.5563, 126.9236, {"cuisine_korean": False, "spicy_focused": False})
    _pin(a, map_id, "K", place_ids)
    h = a.post(f"/maps/{map_id}/pins", json={"category": "음식점", "source": "search", "place_id": "kakao:H",
                                            "place_name": "홍대 라멘집", "lat": 37.5563, "lng": 126.9236})
    assert h.status_code == 201, h.text
    assert a.put(f"/pins/{h.json()['id']}/reaction", json={"type": "like"}).status_code == 200
    run_id = _run(a, map_id, center=(PLACES["K"][1], PLACES["K"][2]), monkeypatch=monkeypatch)
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200, f"{result.status_code} {result.text}"
    assert result.json()["candidates"]


# ───────────────────────── D21 — 카카오 힌트 검증 ─────────────────────────

def _kakao_url_of(db, source_id):
    return db.execute(text("SELECT kakao_place_url FROM places WHERE source_id = :s"), {"s": source_id}).scalar_one()


def test_d21_malformed_kakao_id_is_not_turned_into_a_stored_link(members, place_ids, db_session):
    a, _, map_id = members
    name, lat, lng, _ = PLACES["K"]
    r = a.post(f"/maps/{map_id}/pins", json={"category": "음식점", "source": "search",
                                            "place_id": "kakao:../../evil?x=1#frag", "place_name": name, "lat": lat, "lng": lng})
    stored = _kakao_url_of(db_session, "K")
    assert r.status_code == 422 or stored is None, f"형식이 잘못된 카카오 ID가 링크로 저장됐다: {stored}"


def test_d21_oversized_place_id_is_rejected(members, place_ids):
    a, _, map_id = members
    name, lat, lng, _ = PLACES["K"]
    r = a.post(f"/maps/{map_id}/pins", json={"category": "음식점", "source": "search",
                                            "place_id": "kakao:" + "9" * 20000, "place_name": name, "lat": lat, "lng": lng})
    assert r.status_code == 422, f"길이 제한이 없어 {len(r.text)}바이트 응답과 함께 {r.status_code}"


# ───────────────────────── D25 — ② 글자 에코 ─────────────────────────

def test_d25_planner_output_with_decomposed_hangul_is_accepted():
    """모델이 같은 글자를 자모 분리형(NFD)으로 돌려줘도(눈에 같아 보인다) ②가 통째로 실패하면 run 생성이 막힌다."""
    from llm.schemas import PlannedCondition, PlannedReason, PlanningOutput
    from llm.service import merge_planned

    raw = [{"author_id": "u1", "source": "reaction", "text": "한식 말고 다른 거", "badge": "required"}]
    echoed = unicodedata.normalize("NFD", raw[0]["text"])
    output = PlanningOutput(reasons=[PlannedReason(index=0, text=echoed, conditions=[
        PlannedCondition(fact_key="cuisine_korean", wants=False)])])
    [[line]] = merge_planned(raw, output)
    assert line.text == raw[0]["text"] and line.fact_key == "cuisine_korean"
