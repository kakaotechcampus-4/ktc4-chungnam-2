"""웹 확인 평가셋(#1216, docs/agent-v2.md 6.8 「평가」) — 모델 없이 평가셋 자체를 본다(기본 테스트에 들어간다).

실제 모델 평가는 run_web_eval.py가 한다(10개 × 3회, 사용자 확인 뒤). 여기서는 6.8의 다섯 종류가 모두 있는지, 동네가 운영과 같은 계산
(places.api.neighborhood)인지, 특징 이름이 근거 화면과 같은 이름(recommend.api.fact_labels)인지 본다.
"""

import json
from pathlib import Path

import pytest

from places import api as places_api
from recommend import api as recommend_api

CASES = json.loads(Path(__file__).with_name("web_cases.json").read_text(encoding="utf-8"))
KINDS = {"many_posts", "few_posts", "missing", "same_name", "mixed_reviews"}


def test_cases_cover_the_five_kinds():
    assert len({c["id"] for c in CASES}) == len(CASES) == 10
    assert {c["kind"] for c in CASES} == KINDS
    assert all(c["expect"] == "not_found" for c in CASES if c["kind"] == "missing")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case_input_is_what_production_sends(case):
    """모델 입력은 장소 이름·동네·특징 이름뿐이고, 그 셋을 운영과 같은 함수로 만든 값이다."""
    if case["address"] is not None:
        assert case["area"] == places_api.neighborhood(case["address"])
    assert recommend_api.fact_labels()[case["fact_key"]] == case["feature"]
    assert case["expect"] in ("found", "not_found", "either")
