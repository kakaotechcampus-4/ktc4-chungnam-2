"""모델 호출 — 네트워크에 닿는 얇은 셸. ② 사유 구조화와 v2 에이전트 호출(#532)이 여기서 나간다.

엘리스 ML API(OpenAI 호환)를 쓴다. 지원하지 않는 요청 파라미터는 400으로 거절되므로(기획안 13절)
②는 model·messages·response_format 외에는 넘기지 않는다.
여기서는 호출과 응답 검증까지만 한다 — 결과를 어떻게 합칠지는 service.merge_planned(순수 함수)가 한다.
실패는 전부 LlmCallError 하나로 올린다. 조용히 빈 결과로 바꾸지 않는다(가드레일 4·8).

에이전트 진단과 추천 막힘 조언(#587)은 도구를 쓴다. gpt-6-luna는 chat.completions에서 도구를 reasoning_effort="none"일 때만
받는다(그 밖의 값은 400 "Function tools with reasoning_effort are not supported", 2026-10-15 확인). 그래서 이 두 호출은
reasoning_effort="none"을 넘긴다. 신호 순위 호출(agent_prioritize)은 #582에서 지웠다 — 순위는 agent의 코드 규칙이다.
지도 현황 문단(agent_status, #1168)은 도구 없이 구조화 출력만 받고 reasoning_effort="none"이다(#1152 실험 3과 같은 설정).
웹 확인(call_web_check, #1216)만 Responses API(client.responses.create)다 — Chat Completions는 web_search 도구를 받지 않는다(400).
"""

import json
import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Mapping, Optional, Sequence

from openai import APITimeoutError, OpenAI

from common.settings import settings
from llm import usage as usage_log
from llm.prompts import (
    WEB_CHECK_PROMPT, WEB_CHECK_PROMPT_VERSION, WEB_CHECK_SCHEMA, WEB_CHECK_TIMEOUT_SECONDS,
    AGENT_DIAGNOSE_PROMPT_VERSION, AGENT_STATUS_PROMPT, AGENT_STATUS_PROMPT_VERSION, COURSE_DIRECT_PROMPT, COURSE_DIRECT_PROMPT_VERSION,
    COURSE_GOALS_PROMPT, COURSE_GOALS_PROMPT_VERSION, COURSE_TURN_PROMPT, COURSE_TURN_PROMPT_VERSION,
    PLAN_EVIDENCE_PROMPT,
)
from llm.schemas import (
    AgentFailureReason, AgentUsage, CourseDirectTurn, CourseGoalSet, CourseTurn, DiagnosisOutput, PlanningOutput,
    StatusOutput, WebAnswer, WebCheckOutput,
)

# POST /runs 요청 안에서 동기로 도는 호출이라 길게 기다리지 않는다. 재시도도 안 한다 —
# 실패하면 어차피 RECOMMEND_FAILED이고, 재시도는 요청 지연만 두 배로 만든다.
_TIMEOUT_SECONDS = 15
_MAX_RETRIES = 0

log = logging.getLogger("pingo.llm")

_client: Optional[OpenAI] = None


class LlmCallError(RuntimeError):
    """모델 호출 실패·응답 검증 실패. 메시지에 키·요청 본문을 넣지 않는다.

    reason은 에이전트 호출이 실패 결과(AgentCallFailed)로 바꿀 때 쓰는 분류다. ②는 쓰지 않는다."""

    def __init__(self, message: str, *, reason: AgentFailureReason = "call_failed"):
        super().__init__(message)
        self.reason = reason


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


def _record(
    call: str, prompt_version: Optional[str], completion: Any, outcome: str, started: float, batch_size: Optional[int] = None,
    web_searches: int = 0,
) -> None:
    """llm_calls 한 행(#870). 실패한 호출도 남긴다 — 응답이 있었으면(잘린 응답, 거절) 그 토큰도 비용이다. batch_size는 ②가
    한 호출에 보낸 사유 수(#848), web_searches는 웹 확인 응답 안의 검색 횟수(#1216)."""
    usage_log.record_call(
        call=call, prompt_version=prompt_version, completion=completion, outcome=outcome, elapsed_ms=_elapsed_ms(started),
        batch_size=batch_size, web_searches=web_searches,
    )


PER_CALL_TIMEOUT_SECONDS = _TIMEOUT_SECONDS   # 호출 하나의 타임아웃(클라이언트 기본). 호출 쪽이 남은 시간으로 더 줄일 수 있다(#848)


def call_planner(client: Any, reasons: Sequence[Mapping[str, Any]], *, timeout: float | None = None) -> PlanningOutput:
    """② 한 묶음 호출. timeout이 있으면 이 호출의 타임아웃을 그 값으로 줄인다(create 시간 상한의 남은 시간, #848) — 없으면 클라이언트 기본이다."""
    started = time.monotonic()
    try:
        completion = client.chat.completions.parse(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": PLAN_EVIDENCE_PROMPT},
                {"role": "user", "content": _user_payload(reasons)},
            ],
            response_format=PlanningOutput,
            **({} if timeout is None else {"timeout": timeout}),
        )
        message = completion.choices[0].message
    except Exception as exc:  # noqa: BLE001 — 예상 못 한 예외도 원인 타입만 남기고 같은 실패로 올린다
        log.warning(
            "사유 구조화 호출 실패: model=%s batch=%d %s elapsed_ms=%d",
            settings.llm_model, len(reasons), _failure_fields(exc), _elapsed_ms(started),
        )
        _record("plan_evidence", None, getattr(exc, "completion", None), _agent_failure_reason(exc), started, len(reasons))
        raise LlmCallError(f"사유 구조화 호출 실패: {type(exc).__name__}") from exc
    if getattr(message, "refusal", None):
        # 거절 문구(refusal 본문)는 모델 응답이라 남기지 않는다.
        log.warning("사유 구조화 거절: model=%s batch=%d elapsed_ms=%d", settings.llm_model, len(reasons), _elapsed_ms(started))
        _record("plan_evidence", None, completion, "refusal", started, len(reasons))
        raise LlmCallError("모델이 사유 구조화를 거절했다")
    if message.parsed is None:
        log.warning("사유 구조화 빈 응답: model=%s batch=%d elapsed_ms=%d", settings.llm_model, len(reasons), _elapsed_ms(started))
        _record("plan_evidence", None, completion, "empty", started, len(reasons))
        raise LlmCallError("구조화 응답이 비어 있다")
    _record("plan_evidence", None, completion, "ok", started, len(reasons))
    usage = getattr(completion, "usage", None)
    log.info(
        "사유 구조화 성공: model=%s batch=%d elapsed_ms=%d prompt_tokens=%s completion_tokens=%s",
        settings.llm_model, len(reasons), _elapsed_ms(started),
        getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
    )
    return message.parsed


# ---------- v2 계획 보조 에이전트 (#532) ----------


def _agent_failure_reason(exc: BaseException) -> AgentFailureReason:
    if isinstance(exc, APITimeoutError):
        return "timeout"
    if isinstance(exc, ValueError):  # parse가 응답을 스키마로 검증하다 낸 ValidationError(ValueError의 하위), JSON 깨짐
        return "invalid_schema"
    return "call_failed"


# agent 호출 한 번의 사용량 모으기(#564). service.agent_diagnose가 metering()으로 열고, 그 안의 왕복마다
# _agent_parse가 더한다. planner 시그니처를 바꾸지 않고 모으려고 컨텍스트 변수를 쓴다(스텁 planner는 닿지 않아 0이다).
_usage_meter: ContextVar[Optional[AgentUsage]] = ContextVar("agent_usage_meter", default=None)


@contextmanager
def metering() -> Iterator[AgentUsage]:
    """이 블록 안의 에이전트 왕복 사용량을 내준 AgentUsage에 더한다. 블록이 예외로 끝나도 그때까지 더한 값은 남는다."""
    usage = AgentUsage()
    token = _usage_meter.set(usage)
    try:
        yield usage
    finally:
        _usage_meter.reset(token)


def _meter_request(prompt_version: str) -> None:
    usage = _usage_meter.get()
    if usage is not None:
        usage.model = settings.llm_model
        usage.prompt_version = prompt_version


def _meter_response(completion: Any) -> None:
    usage = _usage_meter.get()
    counts = getattr(completion, "usage", None)
    if usage is not None and counts is not None:
        usage.tokens_in += getattr(counts, "prompt_tokens", None) or 0
        usage.tokens_out += getattr(counts, "completion_tokens", None) or 0


def _agent_parse(client: Any, *, call: str, what: str, context: str, prompt_version: str, **kwargs: Any) -> Any:
    """에이전트 호출 한 번(chat.completions.parse). 응답 message를 돌려준다 — parsed가 있거나 도구 호출이 있다.

    로그는 ②와 같은 규칙이다(#390): 실패는 모델명·예외 클래스·status_code·request_id·소요 ms만, 성공은 토큰 수만 남긴다.
    입력(신호, 사유)과 응답 본문은 남기지 않는다. 사용량은 응답이 오면 거절·빈 응답이어도 더한다(#564).
    call은 llm_calls.call(#870)이다."""
    started = time.monotonic()
    _meter_request(prompt_version)
    try:
        completion = client.chat.completions.parse(model=settings.llm_model, **kwargs)
        _meter_response(completion)
        message = completion.choices[0].message
    except Exception as exc:  # noqa: BLE001 — 예상 못 한 예외도 원인 타입만 남기고 같은 실패로 올린다
        log.warning(
            "%s 호출 실패: model=%s %s %s elapsed_ms=%d",
            what, settings.llm_model, context, _failure_fields(exc), _elapsed_ms(started),
        )
        _record(call, prompt_version, getattr(exc, "completion", None), _agent_failure_reason(exc), started)
        raise LlmCallError(f"{what} 호출 실패: {type(exc).__name__}", reason=_agent_failure_reason(exc)) from exc
    if getattr(message, "refusal", None):
        log.warning("%s 거절: model=%s %s elapsed_ms=%d", what, settings.llm_model, context, _elapsed_ms(started))
        _record(call, prompt_version, completion, "refusal", started)
        raise LlmCallError(f"모델이 {what}을 거절했다")
    if message.parsed is None and not getattr(message, "tool_calls", None):
        log.warning("%s 빈 응답: model=%s %s elapsed_ms=%d", what, settings.llm_model, context, _elapsed_ms(started))
        _record(call, prompt_version, completion, "empty", started)
        raise LlmCallError("구조화 응답이 비어 있다", reason="invalid_schema")
    _record(call, prompt_version, completion, "ok", started)
    usage = getattr(completion, "usage", None)
    log.info(
        "%s 성공: model=%s %s elapsed_ms=%d prompt_tokens=%s completion_tokens=%s",
        what, settings.llm_model, context, _elapsed_ms(started),
        getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None),
    )
    return message


def _agent_tool_turn(
    client: Any, messages: Sequence[Mapping[str, Any]], *, tools: Sequence[Mapping[str, Any]], tool_choice: str, turn: int,
    what: str, prompt_version: str, response_format: type,
) -> Any:
    """도구를 쓰는 에이전트 대화의 한 왕복. 모델이 도구를 부르면 message.tool_calls가, 답하면 message.parsed가 있다.

    reasoning_effort="none": gpt-6-luna는 chat.completions에서 도구를 이 값일 때만 받는다(#532).
    parallel_tool_calls=False: 병렬 도구 호출은 strict 인자 스키마가 보장되지 않는다(OpenAI 문서). 상한도 한 번에 하나씩
    세는 편이 단순하다. 엘리스 API는 이 값을 받는다(2026-10-15 확인)."""
    return _agent_parse(
        client, call="agent_diagnose", what=what, context=f"turn={turn} tool_choice={tool_choice}",
        prompt_version=prompt_version,
        messages=list(messages),
        tools=list(tools),
        tool_choice=tool_choice,
        parallel_tool_calls=False,
        reasoning_effort="none",
        response_format=response_format,
    )


def call_agent_diagnosis_turn(
    client: Any, messages: Sequence[Mapping[str, Any]], *, tools: Sequence[Mapping[str, Any]], tool_choice: str, turn: int
) -> Any:
    """진단 대화의 한 왕복. 답은 message.parsed(DiagnosisOutput)."""
    return _agent_tool_turn(
        client, messages, tools=tools, tool_choice=tool_choice, turn=turn,
        what="에이전트 진단", prompt_version=AGENT_DIAGNOSE_PROMPT_VERSION, response_format=DiagnosisOutput,
    )


def call_agent_status(client: Any, status_input: Mapping[str, Any]) -> StatusOutput:
    """지도 현황 문단 한 번(#1168, agent-v2 8.2). 도구 없이 구조화 출력만 받는다. reasoning_effort="none"은 #1152 실험 3과 같은
    설정이다(약 0.1원·2초). 입력은 코드가 센 칸이고 JSON 문자열로만 넘긴다(프롬프트에 섞지 않는다)."""
    message = _agent_parse(
        client, call="agent_status", what="지도 현황 문단", context="status", prompt_version=AGENT_STATUS_PROMPT_VERSION,
        messages=[
            {"role": "system", "content": AGENT_STATUS_PROMPT},
            {"role": "user", "content": json.dumps(dict(status_input), ensure_ascii=False, default=str)},
        ],
        reasoning_effort="none",
        response_format=StatusOutput,
    )
    if message.parsed is None:  # 도구를 주지 않았는데 도구 호출만 왔다
        raise LlmCallError("지도 현황 문단 응답이 비어 있다", reason="invalid_schema")
    return message.parsed


def call_course_turn(client: Any, turn_input: Mapping[str, Any], *, turn: int) -> CourseTurn:
    """동선 에이전트 턴 한 번(#334). 도구를 tools로 주지 않고 CourseTurn.action으로 받는다 — 그래서 reasoning_effort를
    넘기지 않는다(우선순위 호출과 같다). 입력은 JSON 문자열로만 넘긴다(프롬프트에 섞지 않는다)."""
    message = _agent_parse(
        client, call="course_turn", what="동선 에이전트 턴", context=f"turn={turn}", prompt_version=COURSE_TURN_PROMPT_VERSION,
        messages=[
            {"role": "system", "content": COURSE_TURN_PROMPT},
            {"role": "user", "content": json.dumps(dict(turn_input), ensure_ascii=False, default=str)},
        ],
        response_format=CourseTurn,
    )
    if message.parsed is None:  # 도구를 주지 않았는데 도구 호출만 왔다
        raise LlmCallError("동선 에이전트 턴 응답이 비어 있다", reason="invalid_schema")
    return message.parsed


def _course_parse(
    client: Any, *, call: str, what: str, context: str, prompt_version: str, system: str, payload: Mapping[str, Any], fmt: Any,
) -> Any:
    message = _agent_parse(
        client, call=call, what=what, context=context, prompt_version=prompt_version,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(dict(payload), ensure_ascii=False, default=str)},
        ],
        response_format=fmt,
    )
    if message.parsed is None:
        raise LlmCallError(f"{what} 응답이 비어 있다", reason="invalid_schema")
    return message.parsed


def call_course_goals(client: Any, goals_input: Mapping[str, Any]) -> CourseGoalSet:
    """요청 한 줄 → 목표(#334). 도구 없이 구조화 출력만 받는다."""
    return _course_parse(
        client, call="course_goals", what="동선 목표 세우기", context="goals", prompt_version=COURSE_GOALS_PROMPT_VERSION,
        system=COURSE_GOALS_PROMPT, payload=goals_input, fmt=CourseGoalSet,
    )


def call_course_direct(client: Any, turn_input: Mapping[str, Any], *, turn: int) -> CourseDirectTurn:
    """지휘 턴 한 번(#334). 도구는 CourseDirectTurn.action으로 받는다."""
    return _course_parse(
        client, call="course_direct", what="동선 지휘 턴", context=f"turn={turn}", prompt_version=COURSE_DIRECT_PROMPT_VERSION,
        system=COURSE_DIRECT_PROMPT, payload=turn_input, fmt=CourseDirectTurn,
    )


# ---------- 웹 확인 (#1216, docs/agent-v2.md 6.8) ----------

# 서울(KR) 기준으로 찾는다. 장소 DB가 서울 밖(대전·부산 등)도 있지만 입력의 동네 이름이 지역을 좁힌다(2026-11-03 실험 설정).
# city를 장소의 시·도로 주는 것은 평가(run_web_eval --city-sido, #1221)로 서울 고정과 비교한다 — 운영은 아직 서울이다
WEB_SEARCH_CITY = "Seoul"
WEB_SEARCH_TOOL = {
    "type": "web_search",
    "user_location": {"type": "approximate", "country": "KR", "city": WEB_SEARCH_CITY, "region": WEB_SEARCH_CITY},
}


def web_search_tool(city: str | None = None) -> dict[str, Any]:
    """web_search 도구 설명. city가 없으면 서울(WEB_SEARCH_TOOL). country는 늘 KR이다."""
    if not city:
        return WEB_SEARCH_TOOL
    return {"type": "web_search", "user_location": {"type": "approximate", "country": "KR", "city": city, "region": city}}


def _web_search_calls(response: Any) -> list[Any]:
    return [item for item in (getattr(response, "output", None) or []) if getattr(item, "type", None) == "web_search_call"]


def web_sources(response: Any) -> tuple[str, ...]:
    """그 호출의 검색 출처 URL(web_search_call.action.sources, include로 받은 것). 순서대로, 겹치면 하나. 출처 대조는 이 목록만 쓴다."""
    urls: list[str] = []
    for call in _web_search_calls(response):
        for source in getattr(getattr(call, "action", None), "sources", None) or []:
            url = getattr(source, "url", None)
            if isinstance(url, str) and url and url not in urls:
                urls.append(url)
    return tuple(urls)


def _refused(response: Any) -> bool:
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) == "message":
            if any(getattr(part, "type", None) == "refusal" for part in getattr(item, "content", None) or []):
                return True
    return False


def call_web_check(client: Any, check_input: Mapping[str, Any], *, city: str | None = None) -> WebAnswer:
    """웹 확인 한 번(Responses API). 입력은 장소 이름, 동네, 특징 이름의 JSON 문자열이다(프롬프트에 섞지 않는다).

    tool_choice=required(검색을 하지 않고 답하지 않게), max_tool_calls=1(그래도 검색이 1~2번 나올 수 있다, 실험), reasoning none,
    strict JSON 스키마, include=web_search_call.action.sources(출처 대조에 꼭 필요하다). 타임아웃 30초, 재시도 없음(클라이언트 기본
    0). 로그는 다른 출구와 같은 규칙이다(#390) — 입력, 검색어, 응답 본문, URL은 남기지 않고 검색 횟수와 토큰만 남긴다.
    실패(호출 실패, 시간 초과, 거절, 빈 응답, 스키마 실패)는 LlmCallError다. 응답이 있었으면 검색 횟수와 토큰을 llm_calls에 남긴다.
    city는 검색 위치(web_search_tool) — 모델 입력이 아니다. 운영은 넘기지 않는다(서울)."""
    started = time.monotonic()
    what, call = "웹 확인", "agent_web_check"
    try:
        response = client.responses.create(
            model=settings.llm_model,
            instructions=WEB_CHECK_PROMPT,
            input=json.dumps(dict(check_input), ensure_ascii=False),
            tools=[web_search_tool(city)],
            tool_choice="required",
            max_tool_calls=1,
            reasoning={"effort": "none"},
            text={"format": {"type": "json_schema", "name": "web_check", "strict": True, "schema": WEB_CHECK_SCHEMA}},
            include=["web_search_call.action.sources"],
            timeout=WEB_CHECK_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # noqa: BLE001 — 예상 못 한 예외도 원인 타입만 남기고 같은 실패로 올린다
        log.warning("%s 호출 실패: model=%s %s elapsed_ms=%d", what, settings.llm_model, _failure_fields(exc), _elapsed_ms(started))
        _record(call, WEB_CHECK_PROMPT_VERSION, None, _agent_failure_reason(exc), started)
        raise LlmCallError(f"{what} 호출 실패: {type(exc).__name__}", reason=_agent_failure_reason(exc)) from exc
    searches = len(_web_search_calls(response))

    def fail(outcome: str, message: str, reason: AgentFailureReason) -> LlmCallError:
        log.warning("%s %s: model=%s web_searches=%d elapsed_ms=%d", what, outcome, settings.llm_model, searches, _elapsed_ms(started))
        _record(call, WEB_CHECK_PROMPT_VERSION, response, outcome, started, web_searches=searches)
        error = LlmCallError(message, reason=reason)
        error.web_searches = searches   # 실패해도 검색 요금은 나갔다(평가 기록용)
        return error

    if _refused(response):
        raise fail("refusal", f"모델이 {what}을 거절했다", "call_failed")
    raw = getattr(response, "output_text", None) or ""
    if not raw.strip():
        raise fail("empty", f"{what} 응답이 비어 있다", "invalid_schema")
    try:
        output = WebCheckOutput.model_validate(json.loads(raw))
    except ValueError as exc:   # JSON 깨짐, ValidationError(ValueError의 하위)
        raise fail("invalid_schema", f"{what} 응답이 스키마에 맞지 않는다: {type(exc).__name__}", "invalid_schema") from exc
    _record(call, WEB_CHECK_PROMPT_VERSION, response, "ok", started, web_searches=searches)
    usage = getattr(response, "usage", None)
    log.info(
        "%s 성공: model=%s web_searches=%d elapsed_ms=%d input_tokens=%s output_tokens=%s",
        what, settings.llm_model, searches, _elapsed_ms(started),
        getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None),
    )
    return WebAnswer(output=output, sources=web_sources(response), web_searches=searches)
