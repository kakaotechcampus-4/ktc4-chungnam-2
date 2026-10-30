"""모델 호출 사용량 기록(#870) — 호출 1건마다 llm_calls 한 행.

client의 출구 두 곳(call_planner, _agent_parse)이 응답(또는 실패)마다 `record_call`을 부른다. 무엇을 위해 불렀는지와 지도·사람·실행은
부르는 쪽이 `usage_context`로 붙인다(ContextVar — planner 시그니처를 바꾸지 않는다. client.metering과 같은 방식).

- 라벨(usage_context) 밖의 호출은 기록하지 않고 DEBUG 로그 한 줄만 남긴다 — 평가 스크립트와 live 테스트가 그렇다. 서비스 경로의 호출 지점은
  모두 라벨을 붙인다(llm/tests/test_usage.py, integration/test_llm_usage.py).
- 기록 실패는 본 기능을 막지 않는다. 별도의 짧은 세션으로 쓰고, 예외는 클래스 이름만 로그로 남긴다.
- 비용은 기록 시점의 단가(common.settings)로 계산해 cost_krw에 넣는다. 토큰도 함께 남기므로 단가가 바뀌면 다시 계산할 수 있다.
"""

import logging
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import delete, update
from sqlalchemy.orm import Session

from common.database import SessionLocal
from common.settings import settings
from llm.models import LlmCall

log = logging.getLogger("pingo.llm")

RETENTION_DAYS = 30


@dataclass(frozen=True)
class UsageLabel:
    feature: str
    map_id: Optional[str] = None
    user_id: Optional[str] = None
    run_id: Optional[str] = None
    trace_id: uuid.UUID = field(default_factory=uuid.uuid4)


_label: ContextVar[Optional[UsageLabel]] = ContextVar("llm_usage_label", default=None)


@contextmanager
def usage_context(
    feature: str, *, map_id: Optional[str] = None, user_id: Optional[str] = None, run_id: Optional[str] = None,
) -> Iterator[UsageLabel]:
    """이 블록 안의 모델 호출에 라벨을 붙인다. 블록 하나가 trace_id 하나다. user_id는 사용자가 부른 호출에만 넣는다(서버 호출은 None)."""
    label = UsageLabel(feature, map_id=map_id, user_id=user_id, run_id=None if run_id is None else str(run_id))
    token = _label.set(label)
    try:
        yield label
    finally:
        _label.reset(token)


def current_label() -> Optional[UsageLabel]:
    """지금 붙어 있는 라벨. 호출 지점이 라벨을 붙였는지 테스트가 본다."""
    return _label.get()


@dataclass(frozen=True)
class TokenCounts:
    input_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    output_tokens: int = 0


def token_counts(completion: Any) -> TokenCounts:
    """응답의 usage에서 토큰 수를 읽는다. 엘리스 게이트웨이는 prompt_tokens_details.cached_tokens와 cache_write_tokens를
    준다(2026-10-30 확인). 없거나 응답이 없으면 0이다.

    캐시 미스면 게이트웨이가 cache_write_tokens의 25%를 prompt_tokens에 더해 보고한다(2026-10-30, 같은 요청 두 번:
    1598 = 1279 + 1276 × 0.25). 그래서 input_tokens에는 캐시 쓰기 할증이 이미 들어 있다."""
    usage = getattr(completion, "usage", None)
    if usage is None:
        return TokenCounts()
    details = getattr(usage, "prompt_tokens_details", None)
    return TokenCounts(
        input_tokens=getattr(usage, "prompt_tokens", None) or 0,
        cached_input_tokens=getattr(details, "cached_tokens", None) or 0,
        cache_write_tokens=getattr(details, "cache_write_tokens", None) or 0,
        output_tokens=getattr(usage, "completion_tokens", None) or 0,
    )


def cost_krw(counts: TokenCounts) -> float:
    """원 단위 비용. 입력 중 캐시 몫은 캐시 단가, 나머지는 입력 단가다. cache_write_tokens는 따로 더하지 않는다 — 할증이
    input_tokens에 이미 들어 있다(token_counts). 이 계산이 실제 청구와 같은지는 엘리스 청구서와 대조해야 한다."""
    cached = min(counts.cached_input_tokens, counts.input_tokens)
    return round((
        (counts.input_tokens - cached) * settings.llm_price_input_krw_per_m
        + cached * settings.llm_price_cached_input_krw_per_m
        + counts.output_tokens * settings.llm_price_output_krw_per_m
    ) / 1_000_000, 4)


def _write_row(row: dict[str, Any]) -> None:
    with SessionLocal() as db:
        db.add(LlmCall(**row))
        db.commit()


# 행을 받는 곳. 기본은 DB다. 테스트는 이 값을 바꿔 끼운다(루트 conftest가 기본으로 막는다 — 테스트가 개발 DB에 쓰지 않게).
sink: Callable[[dict[str, Any]], None] = _write_row


def record_call(
    *, call: str, prompt_version: Optional[str], completion: Any, outcome: str, elapsed_ms: int,
    batch_size: Optional[int] = None,
) -> None:
    """출구가 응답마다 부른다. completion은 응답(실패면 예외에 붙은 응답이나 None). 예외를 밖으로 던지지 않는다."""
    label = _label.get()
    counts = token_counts(completion)
    if label is None:
        log.debug("라벨 없는 모델 호출 — llm_calls에 남기지 않는다: call=%s input_tokens=%d", call, counts.input_tokens)
        return
    row = {
        "feature": label.feature, "call": call, "trace_id": label.trace_id,
        "map_id": label.map_id, "user_id": label.user_id, "run_id": label.run_id,
        "model": settings.llm_model, "prompt_version": prompt_version,
        "input_tokens": counts.input_tokens, "cached_input_tokens": counts.cached_input_tokens,
        "cache_write_tokens": counts.cache_write_tokens, "output_tokens": counts.output_tokens,
        "cost_krw": cost_krw(counts), "outcome": outcome, "ok": outcome == "ok", "elapsed_ms": elapsed_ms,
        "batch_size": batch_size,
    }
    try:
        sink(row)
    except Exception as exc:  # noqa: BLE001 — 기록 실패가 모델 호출 결과를 바꾸면 안 된다. 클래스 이름만 남긴다
        log.warning("llm_calls 기록 실패: feature=%s call=%s %s", label.feature, call, type(exc).__name__)


def _mark_rows(trace_ids: list[uuid.UUID]) -> None:
    with SessionLocal() as db:
        db.execute(update(LlmCall).where(LlmCall.trace_id.in_(trace_ids), LlmCall.ok.is_(True)).values(discarded=True))
        db.commit()


# 표시를 쓰는 곳. 기본은 DB다. 테스트는 sink처럼 바꿔 끼운다.
discard_sink: Callable[[list[uuid.UUID]], None] = _mark_rows


def mark_discarded(trace_ids: "list[uuid.UUID] | uuid.UUID | None") -> None:
    """이 trace들의 성공한 호출을 「결과가 쓰이지 않았다」로 표시한다(#848) — 모델 비용은 나갔는데 run·근거가 저장되지 않은 경우다.
    기록 실패는 본 기능의 오류를 가리지 않게 클래스 이름만 로그로 남긴다. 원문·키는 다루지 않는다."""
    ids = [trace_ids] if isinstance(trace_ids, uuid.UUID) else list(trace_ids or [])
    if not ids:
        return
    try:
        discard_sink(ids)
    except Exception as exc:  # noqa: BLE001
        log.warning("llm_calls 폐기 표시 실패: %s", type(exc).__name__)


# ---- 계정 수명과 보존 (api.py가 연다) ----

def anonymize_by_user(db: Session, *, user_id: str) -> int:
    return db.execute(update(LlmCall).where(LlmCall.user_id == user_id).values(user_id=None)).rowcount


def reassign_user(db: Session, *, from_user_id: str, to_user_id: str) -> dict[str, int]:
    moved = db.execute(update(LlmCall).where(LlmCall.user_id == from_user_id).values(user_id=to_user_id)).rowcount
    return {"llm_calls": moved}


def purge_old(db: Session, *, now: datetime, older_than_days: int = RETENTION_DAYS) -> dict[str, int]:
    cutoff = now - timedelta(days=older_than_days)
    return {"llm_calls": db.execute(delete(LlmCall).where(LlmCall.created_at < cutoff)).rowcount}
