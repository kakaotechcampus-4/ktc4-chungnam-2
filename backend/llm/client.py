"""② 사유 구조화의 모델 호출 — 네트워크에 닿는 얇은 셸.

엘리스 ML API(OpenAI 호환)를 쓴다. 지원하지 않는 요청 파라미터는 400으로 거절되므로(기획안 13절)
model·messages·response_format 외에는 넘기지 않는다.
여기서는 호출과 응답 검증까지만 한다 — 결과를 어떻게 합칠지는 service.merge_planned(순수 함수)가 한다.
실패는 전부 LlmCallError 하나로 올린다. 조용히 빈 결과로 바꾸지 않는다(가드레일 4·8).
"""

import json
from typing import Any, Mapping, Sequence

from openai import OpenAI, OpenAIError
from pydantic import ValidationError

from common.settings import settings
from llm.prompts import PLAN_EVIDENCE_PROMPT
from llm.schemas import PlanningOutput

_TIMEOUT_SECONDS = 30
_MAX_RETRIES = 1


class LlmCallError(RuntimeError):
    """모델 호출 실패·응답 검증 실패. 메시지에 키·요청 본문을 넣지 않는다."""


def make_client() -> OpenAI:
    if not settings.elice_ml_api_base_url or not settings.elice_ml_api_key:
        raise LlmCallError("ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 설정되지 않았다")
    return OpenAI(
        base_url=settings.elice_ml_api_base_url,
        api_key=settings.elice_ml_api_key,
        timeout=_TIMEOUT_SECONDS,
        max_retries=_MAX_RETRIES,
    )


def _user_payload(reasons: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps(
        [
            {"index": i, "text": r["text"], "badge": r["badge"], "fact_key": r.get("fact_key")}
            for i, r in enumerate(reasons)
        ],
        ensure_ascii=False,
    )


def call_planner(client: Any, reasons: Sequence[Mapping[str, Any]]) -> PlanningOutput:
    try:
        completion = client.chat.completions.parse(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": PLAN_EVIDENCE_PROMPT},
                {"role": "user", "content": _user_payload(reasons)},
            ],
            response_format=PlanningOutput,
        )
        message = completion.choices[0].message
    except (OpenAIError, ValidationError, IndexError) as exc:
        raise LlmCallError(f"사유 구조화 호출 실패: {type(exc).__name__}") from exc
    if getattr(message, "refusal", None):
        raise LlmCallError("모델이 사유 구조화를 거절했다")
    if message.parsed is None:
        raise LlmCallError("구조화 응답이 비어 있다")
    return message.parsed
