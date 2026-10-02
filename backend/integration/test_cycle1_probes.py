"""
점검 루프 1회차 탐색 배치 — 게시 반복·순위·탈퇴·이벤트 페이로드·입력 제한.

처음에는 **올바른 동작**을 그대로 단언하는 일반 테스트로 쓰고 돌려서, 실패한 것만 결함으로 확정한다
(확정되면 이슈 번호와 함께 `xfail(strict=True, raises=AssertionError)`로 바꾼다).
"""

import pytest
from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _events, _pin, _recommend, fake_planner, members, own_db, place_ids, real_client,
)


# ───────────────────────── 게시 ─────────────────────────

def test_publish_twice_is_idempotent_and_emits_one_event(members, place_ids, fake_planner, db_session):
    a, b, map_id = members
    _, candidates = _recommend(a, b, map_id, place_ids)
    first = a.post(f"/candidates/{candidates[0]['id']}/publish")
    second = a.post(f"/candidates/{candidates[0]['id']}/publish")
    assert first.status_code == 200 and second.status_code == 200, (first.text, second.text)
    assert first.json()["id"] == second.json()["id"], "같은 후보를 두 번 게시해도 핀은 하나"
    assert len(_events(db_session, map_id, "pin.published")) == 1


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D8 — 게시된 AI 핀에 place_source가 없다(가드레일 5). #242")
def test_published_ai_pin_keeps_reason_checks_fulfillment_and_source(members, place_ids, fake_planner):
    """가드레일 5 — 게시된 핀에도 이유·체크·구성원 충족 집계·출처가 붙는다."""
    a, b, map_id = members
    _, candidates = _recommend(a, b, map_id, place_ids)
    pin = a.post(f"/candidates/{candidates[0]['id']}/publish").json()
    assert pin["reason"], "게시 핀에 추천 이유"
    assert pin["checks"], "게시 핀에 조건별 체크"
    assert "member_fulfillment" in pin, "게시 핀에 구성원 충족 집계(0/0이어도 필드는 있어야 한다)"
    assert pin["place_name"]
    assert pin.get("place_source"), "게시 핀에 출처(가드레일 5: 출처가 항상 붙는다)"


def test_retry_after_publish_keeps_ranks_unique(members, place_ids, fake_planner):
    a, b, map_id = members
    run_id, candidates = _recommend(a, b, map_id, place_ids)
    assert a.post(f"/candidates/{candidates[0]['id']}/publish").status_code == 200
    assert a.post(f"/runs/{run_id}/retry").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    ranks = [c["rank"] for c in result.json()["candidates"]] if result.status_code == 200 else []
    assert len(ranks) == len(set(ranks)), f"순위가 겹친다: {ranks}"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D15 — 스펙은 404 AI_PIN_PRIVATE, 코드는 403 FORBIDDEN(결정 대기). #246")
def test_non_author_publish_status_matches_spec(members, place_ids, fake_planner):
    """스펙은 비작성자의 게시를 404 AI_PIN_PRIVATE로 선언한다(코드는 403이라는 보고)."""
    a, b, map_id = members
    _, candidates = _recommend(a, b, map_id, place_ids)
    r = b.post(f"/candidates/{candidates[0]['id']}/publish")
    assert (r.status_code, r.json().get("code")) == (404, "AI_PIN_PRIVATE")


# ───────────────────────── 이벤트 페이로드 ─────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D13 — run.candidates_ready가 Candidate 필수 필드를 싣지 않는다. #241")
def test_candidates_ready_event_payload_has_the_candidate_fields(members, place_ids, fake_planner, db_session):
    a, b, map_id = members
    _recommend(a, b, map_id, place_ids)
    events = _events(db_session, map_id, "run.candidates_ready")
    assert events, "실행이 끝나면 요청자에게 run.candidates_ready가 간다"
    for event in events:
        assert event.channel == "private" and event.recipient_user_id == "user_a"
        for cand in event.payload.get("candidates", []):
            assert {"id", "rank", "checks", "reason", "member_fulfillment", "visibility", "permissions"} <= set(cand), sorted(cand)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D14 — shortlist.changed가 행위자의 my_reaction을 공개 채널로 보낸다. #241")
def test_shortlist_changed_event_does_not_leak_actors_my_reaction(members, place_ids, fake_planner, db_session):
    a, b, map_id = members
    k = _pin(a, map_id, "K", place_ids)
    assert a.put(f"/pins/{k}/reaction", json={"type": "like"}).status_code == 200
    assert a.post(f"/maps/{map_id}/shortlist", json={"pin_id": k}).status_code in (200, 201)
    for event in _events(db_session, map_id, "shortlist.changed"):
        assert event.channel == "public"
        assert "my_reaction" not in (event.payload.get("item") or {}).get("pin", {}) or \
            event.payload["item"]["pin"]["my_reaction"] is None, "공개 채널에 행위자의 내 반응이 실린다"


# ───────────────────────── 탈퇴 ─────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D20 — 탈퇴한 구성원이 member_count에 남는다. #245")
def test_withdrawn_member_is_not_counted_in_member_count(members, place_ids):
    a, b, map_id = members
    assert len(a.get(f"/maps/{map_id}/members").json()) == 2
    assert b.post("/auth/withdraw").status_code == 204
    assert a.get(f"/maps/{map_id}").json()["member_count"] == 1, "탈퇴한 사람이 구성원 수에 남아 준비 판정(N)을 부풀린다"


def test_withdrawn_member_does_not_raise_the_readiness_bar(members, place_ids):
    """2명 중 1명이 반응 → 준비 완료(ceil(2/2)=1). b가 탈퇴해도(N=1) 계속 준비 완료여야 한다 — 반대로 N이 그대로 2면 같은 결과라 3명으로 본다."""
    a, b, map_id = members
    k = _pin(a, map_id, "K", place_ids)
    assert a.put(f"/pins/{k}/reaction", json={"type": "like"}).status_code == 200
    assert b.post("/auth/withdraw").status_code == 204
    ready = a.get(f"/maps/{map_id}/recommend/readiness").json()["음식점"]
    assert ready["required_count"] == 1, ready


# ───────────────────────── 삭제된 핀의 사유 ─────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D12 — 핀 삭제 시 그 핀의 알러지 사유가 근거에서 사라진다. #243")
def test_safety_reason_survives_deleting_its_pin(members, place_ids, fake_planner):
    """누가 핀을 지워도(구성원 누구나 삭제 가능) 다른 사람의 알러지 사유가 사라져 위험한 추천이 나가면 안 된다."""
    a, b, map_id = members
    k = _pin(a, map_id, "K", place_ids)
    s = _pin(a, map_id, "S", place_ids)
    assert b.put(f"/pins/{k}/reaction", json={"type": "against", "reason_text": "조개 알러지"}).status_code == 200
    assert a.put(f"/pins/{s}/reaction", json={"type": "like"}).status_code == 200      # 준비 판정은 통과시킨다
    assert a.delete(f"/pins/{k}").status_code == 204
    run = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    keys = {e["fact_key"] for e in a.get(f"/runs/{run.json()['id']}/evidence").json()}
    assert "contains_shellfish" in keys, "삭제된 핀에 남겨 둔 알러지 사유가 근거에서 사라졌다"


# ───────────────────────── 입력 제한·선택 본문 ─────────────────────────

@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D19 — title 100자 제한 미적용. #244")
def test_map_title_longer_than_100_is_rejected(members):
    a, _, _ = members
    r = a.post("/maps", json={"title": "가" * 101, "start_date": "2026-11-01", "end_date": "2026-11-02",
                              "region": {"label": "x", "lat": 37.5, "lng": 127.0}})
    assert r.status_code == 422, "스펙: title maxLength 100"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D19 — regions/confirm 본문이 필수로 처리된다(스펙은 선택). #244")
def test_regions_confirm_without_body_is_ok(members, place_ids, fake_planner):
    a, b, map_id = members
    run_id, _ = _recommend(a, b, map_id, place_ids, executed=False)
    assert a.post(f"/runs/{run_id}/regions/confirm").status_code == 200, "스펙: requestBody는 선택"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="D19 — evidence PATCH 본문이 필수로 처리된다(스펙은 선택). #244")
def test_evidence_patch_empty_body_is_ok(members, place_ids, fake_planner):
    a, b, map_id = members
    run_id, _ = _recommend(a, b, map_id, place_ids, executed=False)
    assert a.patch(f"/runs/{run_id}/evidence").status_code == 200, "스펙: requestBody는 선택"
