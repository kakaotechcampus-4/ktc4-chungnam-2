"""backend/llm 비즈니스 로직 — 모델 호출 3곳(plan_evidence/label_place/rank_candidates).

② plan_evidence는 LLM_MODE=real일 때 Luna를 실제로 부른다(#116). LLM_MODE=dev면 기존
스텁(입력을 스키마로 검증·통과)이다. ③-a-1 label_place, ③-b rank_candidates는 아직 고정 응답
스텁이다(backend/llm/CLAUDE.md "우선순위" 절) — 시그니처는 최종 형태(입력=구조화 가능한 값,
출력=schemas.py 스키마)로 미리 맞춰둔다.

세 함수 모두 값을 지어내지 않는다: 판단 근거가 없으면 항상 unknown/None을 반환한다
(backend/llm/CLAUDE.md "넘지 말 것"). 실격 여부 판단·unknown_policy 적용은 이 모듈의
책임이 아니다 — recommend가 한다(가드레일 7).
"""

import logging
import re
import unicodedata
from functools import partial
from typing import Any, Callable, Mapping, Optional, Sequence

from common.adapters import select
from common.errors import AppError
from common.settings import settings
from llm.client import LlmCallError, call_planner, get_client
from llm.schemas import (
    EvidenceLine, FactKey, PlaceFactLabel, PlannedCondition, PlannedReason, PlanningOutput, RankedCandidate,
)

log = logging.getLogger("pingo.llm")

# 입력 글마다 근거 줄 묶음 하나(#419) — 바깥 리스트는 입력과 개수·순서가 같다.
EvidencePlanner = Callable[[Sequence[Mapping[str, Any]]], list[list[EvidenceLine]]]


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


MIN_RADIUS_M = 50
MAX_RADIUS_M = 20_000


_INVISIBLE = re.compile(r"[​-‏⁠﻿­\s]+")


def _normalize(text: str) -> str:
    """비교용 정규화 — NFC로 합치고 제로폭 문자·공백을 전부 뺀다. 눈에 같은 글자(자모 분리형 한글 등)를
    같다고 본다. 결과 text에는 쓰지 않는다(결과는 항상 입력 원문)."""
    return _INVISIBLE.sub("", unicodedata.normalize("NFC", text))


def _merge_conditions(conditions: Sequence[PlannedCondition]) -> list[tuple[str, Optional[bool]]]:
    """같은 키가 한 글에서 여러 번 나오면 하나로 합친다(#419). 순서는 처음 나온 순서다.
    방향이 엇갈리면(true와 false) 어느 쪽인지 지어내지 않고 null이다."""
    directions: dict[str, set[bool]] = {}
    for condition in conditions:
        seen = directions.setdefault(condition.fact_key, set())
        if condition.wants is not None:
            seen.add(condition.wants)
    merged: list[tuple[str, Optional[bool]]] = []
    for key, seen in directions.items():
        if len(seen) == 1:
            wants: Optional[bool] = next(iter(seen))
        else:
            wants = None
        merged.append((key, wants))
    return merged


def _split_reason(base: EvidenceLine, planned: PlannedReason) -> list[EvidenceLine]:
    """입력 글 한 줄 → 근거 줄 1개 이상(#419). 조건이 없으면 키 없는 줄 하나, 여럿이면 조건마다 하나.

    입력에 fact_key가 이미 있으면(칩처럼 정해진 줄) 나누지 않는다 — 키는 입력 값이고, 방향은 입력에
    없을 때만 같은 키 조건에서 가져온다. 반경은 입력 글당 하나라 첫 줄에만 붙인다."""
    radius = planned.circle_radius_m
    if radius is None or not MIN_RADIUS_M <= radius <= MAX_RADIUS_M:
        radius = base.circle_radius_m

    if base.fact_key is not None:
        same_key = [c for c in planned.conditions if c.fact_key == base.fact_key]
        planned_wants = _merge_conditions(same_key)[0][1] if same_key else None
        conditions = [(base.fact_key, base.wants if base.wants is not None else planned_wants)]
    else:
        conditions = _merge_conditions(planned.conditions) or [(None, None)]

    return [
        base.model_copy(update={
            "fact_key": fact_key,
            "wants": wants if fact_key is not None else None,
            "circle_radius_m": radius if position == 0 else None,
            "circle_anchor_pin_id": base.circle_anchor_pin_id if position == 0 else None,
        })
        for position, (fact_key, wants) in enumerate(conditions)
    ]


def merge_planned(
    inputs: Sequence[Mapping[str, Any]], output: PlanningOutput
) -> list[list[EvidenceLine]]:
    """모델 응답을 입력에 합친다(순수 함수). 돌려주는 바깥 리스트는 입력과 개수·순서가 같다 — i번째
    묶음이 i번째 입력 글에서 나온 근거 줄들이고, 묶음마다 1줄 이상이다(#419).

    모델이 정하는 건 조건(fact_key·wants, 입력에 없을 때)과 circle_radius_m뿐이다 — badge·author·text·
    source를 포함한 나머지는 전부 입력 값이고, 나눠진 줄들도 그대로 물려받는다.
    badge를 모델이 못 바꾸는 이유: 격하는 제약 완화(가드레일 4)이고, 격상도 사유 텍스트에 섞인
    지시문이 다른 사람 줄을 required로 올리는 통로가 된다. 줄 사이가 섞이지 않게 줄 단위로만 합친다.

    응답은 순서로 합친다 — 개수가 다르거나 index가 위치와 다르면 ValueError다. 결과 text는 항상 입력
    원문이고, 모델이 돌려준 text는 줄이 섞이지 않았는지 보는 확인용이다(NFC·제로폭·공백 제거 후 비교,
    그래도 다르면 지어내거나 섞은 것이라 ValueError).
    반경은 MIN_RADIUS_M~MAX_RADIUS_M 밖이면 무시한다 — 비정상 값은 후보를 전멸시킨다."""
    reasons = output.reasons
    if len(reasons) != len(inputs):
        raise ValueError(f"응답 개수({len(reasons)})가 입력 개수({len(inputs)})와 다르다")

    groups: list[list[EvidenceLine]] = []
    for position, (raw, planned) in enumerate(zip(inputs, reasons)):
        base = EvidenceLine(**raw)
        if planned.index != position:
            raise ValueError(f"응답 index({planned.index})가 위치({position})와 다르다")
        if _normalize(planned.text) != _normalize(base.text):
            raise ValueError("응답 text가 입력 text와 다르다")
        groups.append(_split_reason(base, planned))
    return groups


def _passthrough_planner(raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[EvidenceLine]]:
    return [[EvidenceLine(**reason)] for reason in raw_reasons]


# 엘리스 게이트웨이가 비스트리밍 응답을 2000토큰으로 제한한다(#325). 사유 한 줄의 응답(text 에코 + 조건
# 몇 개)이 70토큰 안팎이라 한 호출에 10개씩만 보낸다. 묶음은 순차로 부른다(동시 호출은 상한·429 위험).
PLAN_BATCH_SIZE = 10


def _model_planner(client: Any, raw_reasons: Sequence[Mapping[str, Any]]) -> list[list[EvidenceLine]]:
    _passthrough_planner(raw_reasons)  # 입력 shape부터 검증 — 깨진 입력으로 모델을 부르지 않는다
    groups: list[list[EvidenceLine]] = []
    for start in range(0, len(raw_reasons), PLAN_BATCH_SIZE):
        batch = raw_reasons[start:start + PLAN_BATCH_SIZE]
        # index는 묶음마다 0부터라 묶음 단위로 합친다. 한 묶음이 실패하면 LlmCallError·ValueError가
        # 그대로 올라간다 — 부분 결과를 지어내지 않는다.
        groups.extend(merge_planned(batch, call_planner(client, batch)))
    return groups


def _dev_evidence_planner() -> EvidencePlanner:
    return _passthrough_planner


def _real_evidence_planner() -> EvidencePlanner:
    return partial(_model_planner, get_client())


get_evidence_planner = select(
    "llm.EvidencePlanner", settings.llm_mode,
    {"dev": _dev_evidence_planner, "real": _real_evidence_planner}, "#116",
)


def plan_evidence(
    raw_reasons: Sequence[Mapping[str, Any]], *, planner: Optional[EvidencePlanner] = None
) -> list[list[EvidenceLine]]:
    """② 사유 → 실격/선호/반경 구조화.

    raw_reasons: recommend가 모은 reaction/manual 원문(EvidenceLine 필드와 동일 shape의 dict).
    반환: 입력 글마다 근거 줄 묶음 하나 — 바깥 리스트는 입력과 개수·순서가 같고(i번째 묶음 = i번째 입력),
    묶음마다 1줄 이상이다. 글 하나에 조건이 여럿이면 묶음 안에 조건마다 줄이 하나씩 있다(#419).
    planner를 안 넘기면 LLM_MODE로 고른 구현을 쓴다(dev=검증·통과 스텁, real=Luna 호출).
    호출·검증이 실패하면 PlanEvidenceFailed — 빈 결과로 바꿔 삼키지 않는다.
    """
    if not raw_reasons:
        return []
    try:
        return (planner or get_evidence_planner())(raw_reasons)
    except (LlmCallError, ValueError) as exc:
        # pydantic.ValidationError는 ValueError의 하위 클래스다(입력 dict가 스키마에 안 맞는 경우 포함).
        # str(exc)는 응답에 넣지 않는다 — ValidationError 문자열에는 입력값(사용자 사유 원문)이 들어 있다(#390).
        cause = exc.__cause__ or exc  # LlmCallError는 원인 예외를 달고 온다 — 응답에는 클래스명만
        log.warning("plan_evidence 실패: %s(%s), 사유 %d개", type(exc).__name__, type(cause).__name__, len(raw_reasons))
        raise PlanEvidenceFailed(f"{type(exc).__name__}({type(cause).__name__}): 사유 구조화에 실패했다") from exc


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
