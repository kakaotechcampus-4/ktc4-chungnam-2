"""② 사유 구조화의 모델 호출 — 네트워크에 닿는 얇은 셸.

엘리스 ML API(OpenAI 호환)를 쓴다. 지원하지 않는 요청 파라미터는 400으로 거절되므로(기획안 13절)
model·messages·response_format 외에는 넘기지 않는다.
여기서는 호출과 응답 검증까지만 한다 — 결과를 어떻게 합칠지는 service.merge_planned(순수 함수)가 한다.
실패는 전부 LlmCallError 하나로 올린다. 조용히 빈 결과로 바꾸지 않는다(가드레일 4·8).
"""

import json
import logging
import time
from typing import Any, Mapping, Optional, Sequence

from openai import OpenAI

from common.settings import settings
from llm.prompts import PLAN_EVIDENCE_PROMPT
from llm.schemas import PlanningOutput

# POST /runs 요청 안에서 동기로 도는 호출이라 길게 기다리지 않는다. 재시도도 안 한다 —
# 실패하면 어차피 RECOMMEND_FAILED이고, 재시도는 요청 지연만 두 배로 만든다.
_TIMEOUT_SECONDS = 15
_MAX_RETRIES = 0

log = logging.getLogger("pingo.llm")

_client: Optional[OpenAI] = None


class LlmCallError(RuntimeError):
    """모델 호출 실패·응답 검증 실패. 메시지에 키·요청 본문을 넣지 않는다."""


def make_client() -> OpenAI:
    if not settings.elice_ml_api_base_url or not settings.elice_ml_api_key:
        # 키 이름만 남긴다 — 값(또는 URL)은 로그에 넣지 않는다.
        missing = [
            name for name, value in (
                ("ELICE_ML_API_BASE_URL", settings.elice_ml_api_base_url),
                ("ELICE_ML_API_KEY", settings.elice_ml_api_key),
            ) if not value
        ]
        log.error("LLM 설정 누락: %s", ", ".join(missing))
        raise LlmCallError("ELICE_ML_API_BASE_URL / ELICE_ML_API_KEY가 설정되지 않았다")
    return OpenAI(
        base_url=settings.elice_ml_api_base_url,
        api_key=settings.elice_ml_api_key,
        timeout=_TIMEOUT_SECONDS,
        max_retries=_MAX_RETRIES,
    )


def get_client() -> OpenAI:
    """프로세스당 하나를 재사용한다(요청마다 커넥션 풀을 새로 만들지 않는다). 설정이 비어 있으면
    캐시하지 않고 매번 LlmCallError — 테스트는 `llm.client._client`를 대역으로 바꾸면 된다."""
    global _client
    if _client is None:
        _client = make_client()
    return _client


def _payload_line(index: int, reason: Mapping[str, Any]) -> dict[str, Any]:
    line: dict[str, Any] = {"index": index, "text": reason["text"], "badge": reason["badge"]}
    # fact_key는 칩에서 이미 정해진 줄에만 보낸다. null을 보내면 모델이 "이미 정해진 값"으로 읽고
    # 키를 붙여야 할 사유에도 null을 돌려준다(#410). 칩 키는 merge_planned가 raw로 지킨다.
    if reason.get("fact_key") is not None:
        line["fact_key"] = reason["fact_key"]
    return line


def _user_payload(reasons: Sequence[Mapping[str, Any]]) -> str:
    return json.dumps([_payload_line(i, r) for i, r in enumerate(reasons)], ensure_ascii=False)


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _failure_fields(exc: BaseException) -> str:
    """실패 로그에 남길 수 있는 필드만 뽑는다 — 예외 문자열(str(exc))은 응답 본문·키 조각을 품을 수 있어 쓰지 않는다."""
    parts = [f"exc={type(exc).__name__}"]
    status_code = getattr(exc, "status_code", None)
    if status_code is not None:
        parts.append(f"status_code={status_code}")
    request_id = getattr(exc, "request_id", None)
    if request_id:
        parts.append(f"request_id={request_id}")
    completion = getattr(exc, "completion", None)  # LengthFinishReasonError — 상한에 걸려 잘린 응답
    if completion is not None:
        usage = getattr(completion, "usage", None)
        choices = getattr(completion, "choices", None) or []
        parts.append(f"completion_tokens={getattr(usage, 'completion_tokens', None)}")
        parts.append(f"finish_reason={getattr(choices[0], 'finish_reason', None) if choices else None}")
    return " ".join(parts)


def call_planner(client: Any, reasons: Sequence[Mapping[str, Any]]) -> PlanningOutput:
    started = time.monotonic()
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
    except Exception as exc:  # noqa: BLE001 — 예상 못 한 예외도 원인 타입만 남기고 같은 실패로 올린다
        log.warning(
            "사유 구조화 호출 실패: model=%s batch=%d %s elapsed_ms=%d",
            settings.llm_model, len(reasons), _failure_fields(exc), _elapsed_ms(started),
        )
        raise LlmCallError(f"사유 구조화 호출 실패: {type(exc).__name__}") from exc
    if getattr(message, "refusal", None):
        # 거절 문구(refusal 본문)는 모델 응답이라 남기지 않는다.
        log.warning("사유 구조화 거절: model=%s batch=%d elapsed_ms=%d", settings.llm_model, len(reasons), _elapsed_ms(started))
        raise LlmCallError("모델이 사유 구조화를 거절했다")
    if message.parsed is None:
        log.warning("사유 구조화 빈 응답: model=%s batch=%d elapsed_ms=%d", settings.llm_model, len(reasons), _elapsed_ms(started))
        raise LlmCallError("구조화 응답이 비어 있다")
    usage = getattr(completion, "usage", None)
    log.info(
        "사유 구조화 성공: model=%s batch=%d elapsed_ms=%d prompt_tokens=%s completion_tokens=%s",
        settings.llm_model, len(reasons), _elapsed_ms(started),
        getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
    )
    return message.parsed
