"""
안전 사유 규칙 (docs/constraints.md "안전 조건 사유는 배지와 무관하게 실격이다", 사용자 결정 2026-10-02) 와
구성원 충족 집계(G1, #246) 재현 테스트.

- △·♥·「+」로 남긴 알러지 사유도 `wants=false`면 실격이다(모름도 제외 — 안전 조건).
- 좋아한다는 사유(`wants=true`)는 hard 키라도 실격이 아니다 — 새 규칙이 좋아하는 것을 실격 처리하면 안 된다(통과해야 하는 회귀 방지).
- 「+」로 직접 추가한 근거 줄도 ②를 거쳐 키·방향이 붙는다.
- `member_fulfillment.total`은 실격 사유를 낸 구성원도 센다.
"""

from datetime import datetime, timezone

import pytest

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _pin, members, own_db, place_ids, real_client,
)
from places import repository
from places.ingest import LabelRow, PlaceRow

NOW = datetime(2026, 10, 2, tzinfo=timezone.utc)


def _extra_place(db, sid, name, lat, lng, facts):
    repository.upsert_places(db, [PlaceRow("permit", sid, name, "음식점", f"서울 {sid}", None, lat, lng, "open")])
    repository.upsert_facts(db, [LabelRow("permit", sid, k, v, "known", 3, NOW) for k, v in facts.items()])
    db.flush()


@pytest.fixture()
def safety_planner(monkeypatch):
    """② 대역 — hard 키에도 방향을 낸다(새 규칙의 전제): 알러지·못 먹는다는 false, 좋아한다는 true."""
    import llm.service as llm_service
    from llm.schemas import EvidenceLine

    def planner(raw_reasons):
        out = []
        for reason in raw_reasons:
            text_ = reason["text"]
            if "조개 알러지" in text_:
                key, wants = "contains_shellfish", False
            elif "매운 거 좋아해" in text_:
                key, wants = "spicy_focused", True
            elif "매운 건 질색" in text_ or "너무 매워요" in text_:
                key, wants = "spicy_focused", False   # 취향 키(#378) — 방향은 wants가 정한다
            else:
                key, wants = None, None
            out.append([EvidenceLine(**{**reason, "fact_key": key, "wants": wants})])
        return out

    monkeypatch.setattr(llm_service, "get_evidence_planner", lambda: planner)


def _candidates(a, map_id):
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    return {c["place_name"] for c in result.json()["candidates"]} if result.status_code == 200 else set(), run_id


@pytest.fixture()
def safe_and_unsafe(db_session):
    """조개 라벨이 거짓으로 확인된 곳 N(안전)과 참인 곳 C(성수 조개구이, 기존) — 나머지는 라벨 없음(모름)."""
    _extra_place(db_session, "N", "성수 담백집", 37.5442, 127.0559,
                 {"contains_shellfish": False, "spicy_focused": False, "cuisine_korean": False})


def test_allergy_reason_on_a_like_reaction_disqualifies(members, place_ids, safety_planner, safe_and_unsafe):
    a, b, map_id = members
    pin = _pin(a, map_id, "K", place_ids)
    assert b.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": "저 조개 알러지 있어요"}).status_code == 200
    names, _ = _candidates(a, map_id)
    assert names == {"성수 담백집"}, f"조개가 참이거나 확인 안 된 곳은 모두 빠져야 한다: {names}"


def test_allergy_reason_added_with_plus_is_structured_and_disqualifies(members, place_ids, safety_planner, safe_and_unsafe):
    a, b, map_id = members
    pin = _pin(a, map_id, "K", place_ids)
    assert a.put(f"/pins/{pin}/reaction", json={"type": "like"}).status_code == 200
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    r = b.patch(f"/runs/{run_id}/evidence", json={"add": [{"text": "저 조개 알러지 있어요"}]})
    assert r.status_code == 200, r.text
    added = next(line for line in b.get(f"/runs/{run_id}/evidence").json() if "조개 알러지" in line["text"])
    assert added.get("fact_key") == "contains_shellfish" and added.get("wants") is False, added
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    names = {c["place_name"] for c in a.get(f"/runs/{run_id}/result").json()["candidates"]}
    assert names == {"성수 담백집"}, names


def test_liking_a_spicy_feature_is_not_a_disqualifier(members, place_ids, safety_planner, db_session):
    """회귀 방지 — "매운 거 좋아해"(♥, spicy_focused, wants=true, 취향 키)가 매운맛 전문 가게를 실격시키면 안 된다."""
    a, b, map_id = members
    _extra_place(db_session, "SP", "성수 마라탕", 37.5443, 127.0557,
                 {"spicy_focused": True, "oily_focused": False, "contains_shellfish": False, "cuisine_korean": False})
    pin = _pin(a, map_id, "K", place_ids)
    assert b.put(f"/pins/{pin}/reaction", json={"type": "like", "reason_text": "매운 거 좋아해"}).status_code == 200
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    names = {c["place_name"] for c in a.get(f"/runs/{run_id}/result").json()["candidates"]}
    assert "성수 마라탕" in names, f"좋아하는 매운맛을 실격 처리했다: {names}"


def test_member_fulfillment_counts_members_who_left_disqualifying_reasons(members, place_ids, safety_planner, db_session):
    from integration.real_places_fixtures import _recommend  # noqa: F401  (픽스처 모듈의 헬퍼 재사용)

    a, b, map_id = members
    k = _pin(a, map_id, "K", place_ids)
    s = _pin(a, map_id, "S", place_ids)
    assert a.put(f"/pins/{k}/reaction", json={"type": "against", "reason_text": "한식 말고 다른 거"}).status_code == 200
    assert b.put(f"/pins/{s}/reaction", json={"type": "against", "reason_text": "너무 매워요"}).status_code == 200
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    cands = a.get(f"/runs/{run_id}/result").json()["candidates"]
    assert cands
    fulfillment = cands[0].get("member_fulfillment") or {}
    assert fulfillment.get("total") == 2 and fulfillment.get("satisfied") == 2, fulfillment



def _narrow_to_b_s_u(a, map_id, place_ids):
    """후보는 3곳까지만 나가므로 K·R·C에 핀을 찍어 B(매운맛 거짓)·S(참)·U(라벨 없음)만 남긴다. K 핀을 돌려준다."""
    k = _pin(a, map_id, "K", place_ids)
    _pin(a, map_id, "R", place_ids)
    _pin(a, map_id, "C", place_ids)
    return k


def _result(a, map_id):
    run_id = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"}).json()["id"]
    a.post(f"/runs/{run_id}/regions/confirm", json={})
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    return {c["place_name"]: c for c in a.get(f"/runs/{run_id}/result").json()["candidates"]}


def test_spicy_against_reason_disqualifies_only_known_true_and_unknown_passes_with_needs_check(
    members, place_ids, safety_planner,
):
    """#378 — 🚫 "너무 매워요"는 취향 키라 라벨이 참인 곳(S)만 실격이고 모름(U)은 통과 + 확인 필요다."""
    a, b, map_id = members
    k = _narrow_to_b_s_u(a, map_id, place_ids)
    assert b.put(f"/pins/{k}/reaction", json={"type": "against", "reason_text": "너무 매워요"}).status_code == 200
    candidates = _result(a, map_id)
    assert set(candidates) == {"성수 분식집", "성수 이름모를집"}, set(candidates)
    spicy = next(ch for ch in candidates["성수 이름모를집"]["checks"] if ch["fact_key"] == "spicy_focused")
    assert spicy["needs_check"] is True and spicy["passed"] is True


def test_spicy_avoid_reason_on_a_like_reaction_is_a_penalty_not_a_disqualifier(members, place_ids, safety_planner):
    """#378 — ♥ "매운 건 질색"(preferred, wants=false)은 실격이 아니라 감점: 매운집(S)은 남되 분식집(B)보다 아래다."""
    a, b, map_id = members
    k = _narrow_to_b_s_u(a, map_id, place_ids)
    assert b.put(f"/pins/{k}/reaction", json={"type": "like", "reason_text": "매운 건 질색이지만 여기는 좋아요"}).status_code == 200
    candidates = _result(a, map_id)
    assert "성수 매운집" in candidates, "♥ 사유는 실격이 아니다"
    assert candidates["성수 매운집"]["rank"] > candidates["성수 분식집"]["rank"]
