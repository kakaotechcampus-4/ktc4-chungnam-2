"""
② 사유 구조화(방향 포함) → create_run → 근거 저장 → 실행(실격·감산) → 결과 → 게시까지 **HTTP로 한 번에**, 실제 장소 DB(PostGIS)에서.

지금까지 어떤 통합 테스트도 이 이음새를 지나지 않았다 — 골든 패스는 dev 어댑터(가짜 장소, 라벨 전부 unknown, ② 통과형)로 돌았고,
`test_wants_example.py`는 근거 줄을 DB에 직접 심었다. 여기서는 ②만 가짜(방향을 내는 구현)로 바꾸고 나머지는 실제로 돈다.

성수 일대의 가상 장소 6곳(라벨 포함)을 직접 적재한다:
  K 한식집(cuisine_korean 참)    R 횟집(raw_fish 참)       B 분식집
  S 매운맛 전문(spicy_focused 참)  C 조개구이(shellfish 참)   U 라벨 없는 집
"""

import uuid

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _pin, fake_planner, members, own_db, place_ids, real_client,
)

def test_wants_direction_flows_from_planner_to_result_on_real_places(members, place_ids, fake_planner, db_session):
    a, b, map_id = members
    k_pin = _pin(a, map_id, "K", place_ids)
    s_pin = _pin(a, map_id, "S", place_ids)
    # a: 한식집에 🚫 "한식 말고 다른 거"   b: 한식집에 ♥ "회 좋아해", 매운집에 🚫 "너무 매워요"
    assert a.put(f"/pins/{k_pin}/reaction", json={"type": "against", "reason_text": "한식 말고 다른 거"}).status_code == 200
    assert b.put(f"/pins/{k_pin}/reaction", json={"type": "like", "reason_text": "회 좋아해"}).status_code == 200
    assert b.put(f"/pins/{s_pin}/reaction", json={"type": "against", "reason_text": "너무 매워요"}).status_code == 200

    run = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]

    evidence = {e["fact_key"]: e for e in a.get(f"/runs/{run_id}/evidence").json() if e["fact_key"]}
    assert evidence["cuisine_korean"]["wants"] is False and evidence["cuisine_korean"]["badge"] == "required"
    assert evidence["cuisine_korean"]["fact_label"] == "한식"
    assert evidence["cuisine_raw_fish"]["wants"] is True and evidence["cuisine_raw_fish"]["badge"] == "preferred"
    assert evidence["spicy_focused"]["badge"] == "required"

    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200, result.text
    candidates = result.json()["candidates"]
    names = [c["place_name"] for c in sorted(candidates, key=lambda c: c["rank"])]

    # K·S는 이미 지도에 핀이 있어 후보에서 빠진다(가드레일 6). U는 매운맛 라벨이 없지만 취향 조건이라 모름은 통과한다(#378).
    # 남는 R·B·C·U 중 횟집이 "회 좋아해"(preferred, wants=true)로 1위, 한식 말고(wants=false)는 넷 다 한식이 아니라 통과.
    # 후보는 3곳까지 고른다(select_top_candidates) — 통과한 4곳 중 3곳이다.
    assert len(names) == 3 and set(names) <= {"성수 횟집", "성수 분식집", "성수 조개구이", "성수 이름모를집"}, names
    assert names[0] == "성수 횟집"
    for c in candidates:
        uuid.UUID(c["id"])
        assert c["reason"] and c["member_fulfillment"]["total"] >= 1 and c["permissions"]["can_publish"] is True


def test_conflicting_directions_exclusion_wins_and_unknown_label_passes_with_needs_check(
    members, place_ids, fake_planner, db_session,
):
    """a는 "한식 말고"(required, false), b는 "한식"을 required로 원한다고 쓴 경우 — 한 명이라도 실격이면 후보에서 내린다(가드레일 9)."""
    a, b, map_id = members
    pin = _pin(a, map_id, "S", place_ids)
    assert a.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": "한식 말고 다른 거"}).status_code == 200
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200, result.text
    names = {c["place_name"] for c in result.json()["candidates"]}
    assert "성수 한식집" not in names, "한식 라벨이 참인 곳은 '한식 말고'로 실격이다"
    # 한식 라벨이 없는 U는 모름 → 통과하되 확인 필요 표시(취향 영역)
    unknown = next((c for c in result.json()["candidates"] if c["place_name"] == "성수 이름모를집"), None)
    assert unknown is not None, "라벨 모름은 취향 조건에서 통과여야 한다"
    korean = next(ch for ch in unknown["checks"] if ch["fact_key"] == "cuisine_korean")
    assert korean["needs_check"] is True and korean["passed"] is True
