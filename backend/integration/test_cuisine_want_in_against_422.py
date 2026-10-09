"""
🚫 사유 안의 음식 종류 "원함"은 선호다(#422). HTTP로 반응 → run 생성 → 근거 → 실행 → 결과까지, 실제 장소 DB(PostGIS)에서.
②만 대역(조건 두 개를 내는 구현)이고 나머지는 실제로 돈다.

🚫 "한식 말고 고기 먹고 싶어요" → "한식 피함"은 꼭 필요한 조건(required) 그대로, "고기구이 원함"은 선호(preferred)로 내린다.
전에는 고기구이 원함도 required라 고깃집이 없는 동네(성수)에서 결과가 0곳이었다(2026-10-09 시험).
"""

from datetime import datetime, timezone

import pytest

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _pin, plan_with, members, own_db, place_ids, real_client,
)
from places import repository
from places.ingest import LabelRow, PlaceRow

NOW = datetime(2026, 10, 9, tzinfo=timezone.utc)
REASON = "한식 말고 고기 먹고 싶어요"
GRILL = "성수 갈빗집"


@pytest.fixture()
def korean_no_grill_planner(monkeypatch):
    """② 대역 — REASON은 조건 두 개(한식 피함, 고기구이 원함), 나머지 글은 조건 없음. 입력 글마다 줄 묶음."""
    from llm.schemas import EvidenceLine

    def planner(raw_reasons):
        out = []
        for reason in raw_reasons:
            if reason["text"] == REASON:
                out.append([EvidenceLine(**{**reason, "fact_key": "cuisine_korean", "wants": False}),
                            EvidenceLine(**{**reason, "fact_key": "cuisine_bbq", "wants": True})])
            else:
                out.append([EvidenceLine(**{**reason, "fact_key": None, "wants": None})])
        return out

    plan_with(monkeypatch, planner)


def _label(db, facts_by_sid):
    repository.upsert_facts(db, [LabelRow("permit", sid, k, v, "known", 3, NOW)
                                 for sid, facts in facts_by_sid.items() for k, v in facts.items()])
    db.flush()


def _run_with_reason(a, b, map_id, place_ids):
    """b가 횟집(R)에 🚫 REASON. R은 핀이 있어 후보에서 빠진다."""
    pin = _pin(a, map_id, "R", place_ids)
    assert b.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": REASON}).status_code == 200
    run = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]
    lines = {line["fact_key"]: line for line in a.get(f"/runs/{run_id}/evidence").json()}
    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    return lines, a.get(f"/runs/{run_id}/result")


def test_wanted_cuisine_in_an_against_reason_is_a_preference_and_ranks_the_grill_first(
    members, place_ids, korean_no_grill_planner, db_session,
):
    a, b, map_id = members
    repository.upsert_places(db_session, [PlaceRow("permit", "G", GRILL, "음식점", "서울 성동구 G", None, 37.5444, 127.0562, "open")])
    _label(db_session, {"G": {"cuisine_bbq": True, "cuisine_korean": False}})

    lines, result = _run_with_reason(a, b, map_id, place_ids)

    assert lines["cuisine_korean"]["badge"] == "required" and lines["cuisine_korean"]["wants"] is False
    assert lines["cuisine_bbq"]["badge"] == "preferred" and lines["cuisine_bbq"]["wants"] is True
    assert result.status_code == 200, result.text
    ranked = [c["place_name"] for c in sorted(result.json()["candidates"], key=lambda c: c["rank"])]
    assert PLACES["K"][0] not in ranked, "한식 피함은 여전히 꼭 필요한 조건이라 한식집은 빠진다"
    assert ranked[0] == GRILL, f"고기구이 원함(선호 +3)으로 갈빗집이 1위여야 한다: {ranked}"


def test_no_grill_nearby_still_recommends_instead_of_zero(members, place_ids, korean_no_grill_planner, db_session):
    """성수 상황 — 반경 안 가게가 모두 '고기구이 아님'으로 확인돼도, 고기구이 원함은 선호라 0곳이 되지 않는다."""
    a, b, map_id = members
    _label(db_session, {sid: {"cuisine_bbq": False} for sid in PLACES})

    lines, result = _run_with_reason(a, b, map_id, place_ids)

    assert lines["cuisine_bbq"]["badge"] == "preferred"
    assert result.status_code == 200, result.text
    names = {c["place_name"] for c in result.json()["candidates"]}
    assert names and PLACES["K"][0] not in names, names
