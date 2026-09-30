"""backend/llm 비즈니스 로직 — 모델 호출 3곳(plan_evidence/label_place/rank_candidates).

② plan_evidence는 LLM_MODE=real일 때 Luna를 실제로 부른다(#116). LLM_MODE=dev면 기존
스텁(입력을 스키마로 검증·통과)이다. ③-a-1 label_place, ③-b rank_candidates는 아직 고정 응답
스텁이다(backend/llm/CLAUDE.md "우선순위" 절) — 시그니처는 최종 형태(입력=구조화 가능한 값,
출력=schemas.py 스키마)로 미리 맞춰둔다.

세 함수 모두 값을 지어내지 않는다: 판단 근거가 없으면 항상 unknown/None을 반환한다
(backend/llm/CLAUDE.md "넘지 말 것"). 실격 여부 판단·unknown_policy 적용은 이 모듈의
책임이 아니다 — recommend가 한다(가드레일 7).
"""

from functools import partial
from typing import Any, Callable, Mapping, Optional, Sequence

from common.adapters import select
from common.errors import AppError
from common.settings import settings
from llm.client import LlmCallError, call_planner, make_client
from llm.schemas import EvidenceLine, FactKey, PlaceFactLabel, PlanningOutput, RankedCandidate

EvidencePlanner = Callable[[Sequence[Mapping[str, Any]]], list[EvidenceLine]]


def _flatten_string_values(data: Mapping[str, Any]) -> list[str]:
    """place_raw_facts 안의 모든 문자열 값을 평탄화한다.

    evidence 대조에 쓸 "실제로 원자료에 있던 텍스트 전체" 목록을 만든다.
    중첩된 list/dict 안의 문자열까지 재귀적으로 뽑아낸다(예: 리뷰 텍스트 배열).
    """
    flattened: list[str] = []

    def _walk(value: Any) -> None:
        if isinstance(value, str):
            flattened.append(value)
        elif isinstance(value, Mapping):
            for nested in value.values():
                _walk(nested)
        elif isinstance(value, (list, tuple, set)):
            for nested in value:
                _walk(nested)

    for value in data.values():
        _walk(value)
    return flattened


class PlanEvidenceFailed(AppError):
    """②가 실패했다 — 사유를 "조건 없음"으로 간주해 통과시키지 않고 추천을 중단한다(가드레일 4·8).
    기존 에러 코드 RECOMMEND_FAILED(500)로 나간다."""

    def __init__(self, reason: str):
        super().__init__("RECOMMEND_FAILED", detail={"stage": "plan_evidence", "reason": reason})


def merge_planned(
    inputs: Sequence[Mapping[str, Any]], output: PlanningOutput
) -> list[EvidenceLine]:
    """모델 응답을 입력에 합친다(순수 함수). 모델이 바꿀 수 있는 건 fact_key(입력에 없을 때)·
    badge 격상·circle_radius_m뿐이다 — 나머지는 전부 입력 값이 이긴다.

    개수·순서·text가 입력과 다르면 모델이 사유를 지어내거나 섞은 것이므로 ValueError다.
    badge 격하는 무시한다: 제약을 AI가 완화하지 않는다(가드레일 4)."""
    lines = output.evidence_lines
    if len(lines) != len(inputs):
        raise ValueError(f"응답 개수({len(lines)})가 입력 개수({len(inputs)})와 다르다")

    merged: list[EvidenceLine] = []
    for raw, planned in zip(inputs, lines):
        base = EvidenceLine(**raw)
        if planned.text != base.text:
            raise ValueError("응답 text가 입력 text와 다르다")
        radius = planned.circle_radius_m
        merged.append(
            base.model_copy(
                update={
                    "fact_key": base.fact_key or planned.fact_key,
                    "badge": "required" if planned.badge == "required" else base.badge,
                    "circle_radius_m": radius if radius is not None and radius > 0 else base.circle_radius_m,
                }
            )
        )
    return merged


def _passthrough_planner(raw_reasons: Sequence[Mapping[str, Any]]) -> list[EvidenceLine]:
    return [EvidenceLine(**reason) for reason in raw_reasons]


def _model_planner(client: Any, raw_reasons: Sequence[Mapping[str, Any]]) -> list[EvidenceLine]:
    _passthrough_planner(raw_reasons)  # 입력 shape부터 검증 — 깨진 입력으로 모델을 부르지 않는다
    return merge_planned(raw_reasons, call_planner(client, raw_reasons))


def _dev_evidence_planner() -> EvidencePlanner:
    return _passthrough_planner


def _real_evidence_planner() -> EvidencePlanner:
    return partial(_model_planner, make_client())


get_evidence_planner = select(
    "llm.EvidencePlanner", settings.llm_mode,
    {"dev": _dev_evidence_planner, "real": _real_evidence_planner}, "#116",
)


def plan_evidence(
    raw_reasons: Sequence[Mapping[str, Any]], *, planner: Optional[EvidencePlanner] = None
) -> list[EvidenceLine]:
    """② 사유 → 실격/선호/반경 구조화.

    raw_reasons: recommend가 모은 reaction/manual 원문(EvidenceLine 필드와 동일 shape의 dict).
    planner를 안 넘기면 LLM_MODE로 고른 구현을 쓴다(dev=검증·통과 스텁, real=Luna 호출).
    호출·검증이 실패하면 PlanEvidenceFailed — 빈 결과로 바꿔 삼키지 않는다.
    """
    if not raw_reasons:
        return []
    try:
        return (planner or get_evidence_planner())(raw_reasons)
    except (LlmCallError, ValueError) as exc:
        # pydantic.ValidationError는 ValueError의 하위 클래스다(입력 dict가 스키마에 안 맞는 경우 포함).
        raise PlanEvidenceFailed(str(exc)) from exc


def label_place(
    place_raw_facts: Mapping[str, Any],
    fact_keys: Sequence[FactKey],
    evidence_by_fact_key: Optional[Mapping[FactKey, str]] = None,
) -> list[PlaceFactLabel]:
    """③-a-1 장소 라벨링 — fact_key마다 confidence(known/unknown) 판정만 반환한다.

    place_raw_facts: docs/architecture.md 3층 모델의 층1·2 원자료(장소 상세, 메뉴, 리뷰 등에서
    이미 수집된 값). 실제 모델 연동 전 v1 스텁은 이 원자료에 해당 fact_key 값이 명시적으로
    있을 때만 known으로 응답하고, 없으면(누락/None) 항상 unknown이다 — 정보가 부족하다고
    값을 지어내지 않는다.

    evidence_by_fact_key: 모델(또는 상위 단계)이 "원자료의 이 부분을 보고 판단했다"고 주장하는
    근거 텍스트. v1 스텁 자체는 evidence를 만들어내지 않지만(주어지지 않으면 항상 None), 이
    인자로 evidence가 들어오면 place_raw_facts의 문자열 값들과 실제로 대조한다 — 평탄화한
    원문 어디에도 부분 문자열로 없으면 근거를 지어낸 것으로 보고 confidence를 unknown으로
    강등하고 value·evidence를 전부 None으로 덮어써서 지어낸 근거가 known으로 새어나가지
    않게 한다.

    반환값은 라벨(판단)일 뿐이다. unknown_policy 적용이나 실격 여부 판단은 하지 않는다
    (recommend의 책임, 가드레일 7).
    """
    evidence_by_fact_key = evidence_by_fact_key or {}
    raw_texts = _flatten_string_values(place_raw_facts)

    labels: list[PlaceFactLabel] = []
    for key in fact_keys:
        value = place_raw_facts.get(key)
        if value is None:
            labels.append(PlaceFactLabel(fact_key=key, confidence="unknown"))
            continue

        evidence = evidence_by_fact_key.get(key)
        if evidence is not None and (
            not evidence.strip() or not any(evidence in text for text in raw_texts)
        ):
            # 공백만 있는 evidence는 근거가 없는 것과 동일하게 취급해 강등한다
            # (pins/core.py validate_reaction이 공백만 있는 reason_text를 처리하는 패턴과 동일) —
            # 그렇지 않으면 evidence=""일 때 "" in text가 항상 True라서 대조가 무력화된다.
            # 원자료 어디에도 없는 근거(지어낸 근거)도 동일하게 강등한다.
            labels.append(PlaceFactLabel(fact_key=key, confidence="unknown"))
            continue

        labels.append(
            PlaceFactLabel(fact_key=key, value=value, confidence="known", evidence=evidence)
        )
    return labels


def rank_candidates(candidate_place_ids: Sequence[str]) -> list[RankedCandidate]:
    """③-b 선호 순위 채점.

    candidate_place_ids: 실격 통과분(recommend가 필터링을 마친 후보)만 들어온다는 전제.
    이 함수는 순위만 매기며 실격 여부는 다시 판단하지 않는다(가드레일 7).
    v1 스텁은 실제 모델 호출 없이 입력 순서를 그대로 순위로 반환하고, 근거가 없으므로
    member_comment는 지어내지 않고 None으로 둔다(5-7-1).
    """
    return [
        RankedCandidate(place_id=place_id, rank=index + 1, member_comment=None)
        for index, place_id in enumerate(candidate_place_ids)
    ]
