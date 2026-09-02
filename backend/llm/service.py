"""backend/llm 비즈니스 로직 — 모델 호출 3곳(plan_evidence/label_place/rank_candidates).

v1은 backend/llm/CLAUDE.md "우선순위" 절 그대로 고정 응답 스텁이다. 실제 LLM API 호출은
모델 확정(#12) 이후 이 파일의 함수 내부만 교체하면 되도록, 시그니처는 최종 형태(입력=구조화
가능한 값, 출력=schemas.py 스키마)로 미리 맞춰둔다.

세 함수 모두 값을 지어내지 않는다: 판단 근거가 없으면 항상 unknown/None을 반환한다
(backend/llm/CLAUDE.md "넘지 말 것"). 실격 여부 판단·unknown_policy 적용은 이 모듈의
책임이 아니다 — recommend가 한다(가드레일 7).
"""

from typing import Any, Mapping, Sequence

from llm.schemas import EvidenceLine, FactKey, PlaceFactLabel, RankedCandidate


def plan_evidence(raw_reasons: Sequence[Mapping[str, Any]]) -> list[EvidenceLine]:
    """② 사유 → 실격/선호/반경 구조화.

    raw_reasons: recommend가 모은 reaction/manual 원문(EvidenceLine 필드와 동일 shape의 dict).
    v1 스텁은 실제 모델 호출 없이 입력을 스키마로 검증·통과시키기만 한다 — 자유 텍스트에서
    fact_key를 추론하는 분류 로직은 모델 연동 이후 단계에서 채운다(품질은 스텁이 자리 잡은
    뒤 끌어올린다).
    """
    return [EvidenceLine(**reason) for reason in raw_reasons]


def label_place(
    place_raw_facts: Mapping[str, Any], fact_keys: Sequence[FactKey]
) -> list[PlaceFactLabel]:
    """③-a-1 장소 라벨링 — fact_key마다 confidence(known/unknown) 판정만 반환한다.

    place_raw_facts: docs/architecture.md 3층 모델의 층1·2 원자료(장소 상세, 메뉴, 리뷰 등에서
    이미 수집된 값). 실제 모델 연동 전 v1 스텁은 이 원자료에 해당 fact_key 값이 명시적으로
    있을 때만 known으로 응답하고, 없으면(누락/None) 항상 unknown이다 — 정보가 부족하다고
    값을 지어내지 않는다.

    반환값은 라벨(판단)일 뿐이다. unknown_policy 적용이나 실격 여부 판단은 하지 않는다
    (recommend의 책임, 가드레일 7).
    """
    labels: list[PlaceFactLabel] = []
    for key in fact_keys:
        value = place_raw_facts.get(key)
        if value is None:
            labels.append(PlaceFactLabel(fact_key=key, confidence="unknown"))
        else:
            labels.append(PlaceFactLabel(fact_key=key, value=value, confidence="known"))
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
