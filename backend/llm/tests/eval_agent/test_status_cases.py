"""지도 현황 문단 평가셋(#1168, docs/agent-v2.md 8.2 「평가」) — 모델 없이 평가셋 자체를 본다(기본 테스트에 들어간다).

실제 모델 평가는 run_status_eval.py가 한다(10개 × 5회). 여기서는 상황이 칸 모양과 맞는지, 기대 상태가 사실과 어긋나지 않는지,
케이스마다 적은 참고 문단이 운영 검증(core.verify_status)을 통과하는지(풀 수 있는 상황인지), 고정 응답 스텁도 통과하는지 본다.
"""

import json
from pathlib import Path

import pytest

from agent import core
from common import categories
from llm import service
from llm.schemas import StatusOutput

CASES = json.loads(Path(__file__).with_name("status_cases.json").read_text(encoding="utf-8"))


def test_ten_cases_cover_the_situations():
    assert len(CASES) == 10 and len({c["id"] for c in CASES}) == 10
    cells = [c["cells"] for c in CASES]
    assert any(c["first_category"] is None and c["first_reason"] is None for c in cells)       # 먼저 볼 곳 없음
    assert any(c["first_category"] is None and c["first_reason"] for c in cells)               # 반응 공백(이유만)
    assert any(c["dday"] < 0 for c in cells) and any(c["dday"] == 0 for c in cells)            # 여행 중, 오늘 출발
    assert any(any(x["stalled"] for x in c["categories"]) for c in cells)
    states = {s for c in CASES for allowed in c["expect_states"].values() for s in allowed}
    assert states == {"decided", "almost", "split_left", "stalled", "few", "gathering", "empty"}   # 일곱 가지 모두


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_is_well_formed_and_solvable(case):
    cells = case["cells"]
    assert [c["category"] for c in cells["categories"]] == list(categories.pinnable())
    assert cells["first_category"] in (None, *categories.pinnable())
    assert set(case["expect_states"]) == set(categories.pinnable())
    by_name = {c["category"]: c for c in cells["categories"]}
    for category, allowed in case["expect_states"].items():
        assert not [s for s in allowed if core._state_conflict(s, by_name[category])], category

    reference = StatusOutput.model_validate({
        "categories": [{"category": c, "state": case["expect_states"][c][0]} for c in categories.pinnable()],
        "paragraph": case["reference"],
    })
    verified = core.verify_status(reference, cells)
    assert verified.ok, verified.record


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_fixed_stub_passes_every_case(case):
    reply = service.agent_status(case["cells"], planner=service.fixed_status_planner)
    assert core.verify_status(reply.result, case["cells"]).ok
