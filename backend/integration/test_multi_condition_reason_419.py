"""
사유 글 하나에 조건이 여럿이면 근거 줄을 조건마다 나눈다(#419). HTTP로 반응 → run 생성 → 근거 → 실행 → 결과까지,
실제 장소 DB(PostGIS)에서. ②만 대역(조건 두 개를 내는 구현)이고 나머지는 실제로 돈다.

전에는 한 줄에 키 하나만 붙여서 "매운 거랑 해산물 둘 다 안 돼요"에서 해산물이 빠지는 식으로 조건이 조용히 사라졌다.
"""

import pytest

from integration.real_places_fixtures import (  # noqa: F401 — 픽스처는 import로 등록된다
    PLACES, _pin, members, own_db, place_ids, real_client,
)

TWO_CONDITIONS = "한식 말고, 매운 것도 싫어요"


@pytest.fixture()
def two_condition_planner(monkeypatch):
    """② 대역 — TWO_CONDITIONS는 조건 두 개(한식 피함, 매운맛 피함), 나머지 글은 조건 없음. 입력 글마다 줄 묶음을 돌려준다."""
    import llm.service as llm_service
    from llm.schemas import EvidenceLine

    def planner(raw_reasons):
        out = []
        for reason in raw_reasons:
            if reason["text"] == TWO_CONDITIONS:
                out.append([EvidenceLine(**{**reason, "fact_key": "cuisine_korean", "wants": False}),
                            EvidenceLine(**{**reason, "fact_key": "spicy_focused", "wants": False})])
            else:
                out.append([EvidenceLine(**{**reason, "fact_key": None, "wants": None})])
        return out

    monkeypatch.setattr(llm_service, "get_evidence_planner", lambda: planner)
    return planner


def _start(a, b, map_id, place_ids):
    """b가 횟집(R)에 🚫 TWO_CONDITIONS. 한식집(K)·매운집(S)은 핀이 없어 조건으로만 빠질 수 있다."""
    pin = _pin(a, map_id, "R", place_ids)
    r = b.put(f"/pins/{pin}/reaction", json={"type": "against", "reason_text": TWO_CONDITIONS})
    assert r.status_code == 200, r.text
    run = a.post(f"/maps/{map_id}/runs", json={"category": "음식점"})
    assert run.status_code == 202, run.text
    return run.json()["id"]


def test_one_reason_with_two_conditions_becomes_two_lines_and_both_filter(members, place_ids, two_condition_planner):
    a, b, map_id = members
    run_id = _start(a, b, map_id, place_ids)

    lines = a.get(f"/runs/{run_id}/evidence").json()
    assert len(lines) == 2, lines
    assert {(line["fact_key"], line["wants"]) for line in lines} == {("cuisine_korean", False), ("spicy_focused", False)}
    assert all(line["text"] == TWO_CONDITIONS and line["badge"] == "required" for line in lines)

    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200, result.text
    names = {c["place_name"] for c in result.json()["candidates"]}
    assert PLACES["K"][0] not in names, "한식 피함 줄로 한식집이 빠져야 한다"
    assert PLACES["S"][0] not in names, "매운맛 피함 줄로 매운집이 빠져야 한다(전에는 조건 하나가 사라졌다)"
    assert names == {PLACES["B"][0], PLACES["C"][0], PLACES["U"][0]}, names   # R은 지도에 핀이 있어 빠진다


def test_turning_off_one_split_line_keeps_the_other_condition(members, place_ids, two_condition_planner):
    """한 줄이 조건 하나라서 「−」로 매운맛 줄만 끄면 한식 조건은 남는다 — 매운집은 다시 후보가 될 수 있고 한식집은 계속 빠진다."""
    a, b, map_id = members
    run_id = _start(a, b, map_id, place_ids)
    lines = b.get(f"/runs/{run_id}/evidence").json()
    spicy = next(line for line in lines if line["fact_key"] == "spicy_focused")
    r = b.patch(f"/runs/{run_id}/evidence", json={"toggle": [{"id": spicy["id"], "is_active": False}]})
    assert r.status_code == 200, r.text
    active = {line["fact_key"]: line["is_active"] for line in r.json()}
    assert active == {"cuisine_korean": True, "spicy_focused": False}

    assert a.post(f"/runs/{run_id}/regions/confirm", json={}).status_code == 200
    assert a.post(f"/runs/{run_id}/execute").status_code == 202
    result = a.get(f"/runs/{run_id}/result")
    assert result.status_code == 200, result.text
    candidates = result.json()["candidates"]
    names = {c["place_name"] for c in candidates}
    assert PLACES["K"][0] not in names
    for c in candidates:
        assert all(ch["fact_key"] != "spicy_focused" or ch["passed"] for ch in c["checks"]), "끈 줄은 실격에 쓰이지 않는다"
