"""backend/llm/CLAUDE.md 완료 정의:
- ②③-a-1③-b 각각의 구조화 출력 스키마를 docs/constraints.md의 fact_key마다 최소 1개씩 커버
- unknown 응답이 실제로 발생하는 경계 케이스(정보 부족한 후보) 테스트
"""

from typing import get_args

import pytest
from pydantic import ValidationError

from llm.schemas import EvidenceLine, FactKey, PlaceFactLabel, RankedCandidate
from llm.service import label_place, plan_evidence, rank_candidates

ALL_FACT_KEYS = get_args(FactKey)

# fact_key별로 "정보가 있을 때" known으로 판정되어야 할 표본값.
# docs/constraints.md 조건별 정의 표의 실격(hard) 6개 + 선호(soft) 4개를 전부 포함한다.
SAMPLE_VALUE_BY_FACT_KEY: dict[FactKey, object] = {
    "contains_shellfish": True,
    "spicy_focused": False,
    "oily_focused": False,
    "price_bucket": "mid",
    "capacity_min": 4,
    "is_crowded_large": False,
    "wait_short": True,
    "quiet": True,
    "comfortable_seat": False,
    "local_flavor": True,
}


def test_sample_values_cover_every_registered_fact_key():
    # 테스트 표본 자체가 레지스트리 전체를 덮는지 먼저 보장한다(회귀 방지).
    assert set(SAMPLE_VALUE_BY_FACT_KEY.keys()) == set(ALL_FACT_KEYS)


class TestLabelPlaceKnown:
    """③-a-1: 원자료에 값이 있으면 known + 그 값을 그대로 반환한다."""

    @pytest.mark.parametrize("fact_key", ALL_FACT_KEYS)
    def test_known_when_raw_fact_present(self, fact_key: FactKey):
        sample_value = SAMPLE_VALUE_BY_FACT_KEY[fact_key]
        place_raw_facts = {fact_key: sample_value}

        [label] = label_place(place_raw_facts, [fact_key])

        assert label.fact_key == fact_key
        assert label.confidence == "known"
        assert label.value == sample_value


class TestLabelPlaceUnknownBoundary:
    """③-a-1 경계 케이스: 정보 부족한 후보는 절대 값을 지어내지 않고 unknown을 반환한다."""

    @pytest.mark.parametrize("fact_key", ALL_FACT_KEYS)
    def test_unknown_when_raw_fact_missing(self, fact_key: FactKey):
        place_raw_facts: dict = {}  # 정보가 전혀 없는 후보

        [label] = label_place(place_raw_facts, [fact_key])

        assert label.confidence == "unknown"
        assert label.value is None

    def test_unknown_when_raw_fact_is_none(self):
        # 키는 있지만 값이 None인 경우(예: 수집 실패)도 known으로 오인하면 안 된다.
        place_raw_facts = {"contains_shellfish": None}

        [label] = label_place(place_raw_facts, ["contains_shellfish"])

        assert label.confidence == "unknown"
        assert label.value is None

    def test_partial_information_place_mixes_known_and_unknown(self):
        # 정보가 일부만 있는 실제 시나리오: 있는 것만 known, 나머지는 unknown이어야 한다.
        place_raw_facts = {"contains_shellfish": True}
        fact_keys = ["contains_shellfish", "spicy_focused", "price_bucket"]

        labels = label_place(place_raw_facts, fact_keys)

        by_key = {label.fact_key: label for label in labels}
        assert by_key["contains_shellfish"].confidence == "known"
        assert by_key["spicy_focused"].confidence == "unknown"
        assert by_key["spicy_focused"].value is None
        assert by_key["price_bucket"].confidence == "unknown"
        assert by_key["price_bucket"].value is None


class TestPlaceFactLabelSchemaGuardsAgainstFabrication:
    """스키마 레벨에서도 unknown+value 조합을 막아 값 지어내기를 원천 차단한다."""

    def test_unknown_with_value_is_rejected(self):
        with pytest.raises(ValidationError):
            PlaceFactLabel(fact_key="contains_shellfish", value=True, confidence="unknown")

    def test_known_without_value_is_rejected(self):
        with pytest.raises(ValidationError):
            PlaceFactLabel(fact_key="contains_shellfish", confidence="known")


class TestPlanEvidence:
    """② 사유 → 구조화. v1 스텁은 검증·통과만 하고 fact_key를 지어내 채우지 않는다."""

    def test_passes_through_structured_reason(self):
        raw = [
            {
                "source": "reaction",
                "text": "갑각류 알러지 있어요",
                "chip_id": "chip_shellfish",
                "badge": "required",
                "fact_key": "contains_shellfish",
            }
        ]

        [evidence] = plan_evidence(raw)

        assert isinstance(evidence, EvidenceLine)
        assert evidence.badge == "required"
        assert evidence.fact_key == "contains_shellfish"

    def test_freeform_reason_without_fact_key_stays_unclassified(self):
        # 자유 텍스트에서 fact_key를 추론하는 건 실제 모델 연동 이후 단계 —
        # v1 스텁이 값을 지어내면 안 된다.
        raw = [{"source": "manual", "text": "그냥 여기 가고 싶어요", "badge": "reference"}]

        [evidence] = plan_evidence(raw)

        assert evidence.fact_key is None


class TestRankCandidates:
    """③-b: 실격 통과분의 순위만 매기고, 근거 없는 코멘트를 지어내지 않는다."""

    def test_assigns_sequential_rank_in_input_order(self):
        candidate_place_ids = ["place-a", "place-b", "place-c"]

        ranked = rank_candidates(candidate_place_ids)

        assert [r.place_id for r in ranked] == candidate_place_ids
        assert [r.rank for r in ranked] == [1, 2, 3]
        assert all(isinstance(r, RankedCandidate) for r in ranked)

    def test_no_fabricated_member_comment(self):
        [ranked] = rank_candidates(["place-a"])

        assert ranked.member_comment is None

    def test_empty_candidates_returns_empty_ranking(self):
        assert rank_candidates([]) == []
