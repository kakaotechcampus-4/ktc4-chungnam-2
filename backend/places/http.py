"""소스 호출 공통 — 타임아웃·제한적 재시도·호출 횟수 로그. 키는 헤더로만 보내고 로그에 안 남긴다."""

from __future__ import annotations

import logging
import threading
import time
from collections import Counter
from typing import Any

import httpx

log = logging.getLogger("pingo.places")

_RETRY_STATUS = {429, 500, 502, 503, 504}


class SourceError(RuntimeError):
    """소스 호출 실패. 폴백 로직이 잡아서 다음 소스로 넘어간다."""


class CallStats:
    """소스별 실제 HTTP 호출 횟수(재시도 포함). 프로세스 수명 동안 누적."""

    def __init__(self) -> None:
        self._counts: Counter[str] = Counter()
        self._lock = threading.Lock()

    def count(self, source: str) -> int:
        with self._lock:
            return self._counts[source]

    def incr(self, source: str) -> int:
        with self._lock:
            self._counts[source] += 1
            return self._counts[source]

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)


class SourceHttp:
    def __init__(self, client: httpx.Client, stats: CallStats, *, retries: int) -> None:
        self._client = client
        self._stats = stats
        self._retries = max(0, retries)

    def request_json(
        self,
        source: str,
        endpoint: str,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        retries: int | None = None,
    ) -> dict[str, Any]:
        attempts = 1 + (self._retries if retries is None else max(0, retries))
        last: str = ""
        for attempt in range(1, attempts + 1):
            started = time.monotonic()
            status: int | str = "error"
            try:
                resp = self._client.request(method, url, headers=headers, params=params, json=json)
                status = resp.status_code
                if status in _RETRY_STATUS and attempt < attempts:
                    last = f"HTTP {status}"
                    continue
                if status >= 400:
                    raise SourceError(f"{source} {endpoint}: HTTP {status}")
                try:
                    return resp.json()
                except ValueError as exc:
                    raise SourceError(f"{source} {endpoint}: 응답이 JSON이 아니다") from exc
            except httpx.TransportError as exc:   # 타임아웃·연결 실패
                status = type(exc).__name__
                last = status
                if attempt >= attempts:
                    raise SourceError(f"{source} {endpoint}: {status}") from exc
            finally:
                total = self._stats.incr(source)
                log.info(
                    "places.call source=%s endpoint=%s status=%s attempt=%d ms=%d total_calls[%s]=%d",
                    source, endpoint, status, attempt, (time.monotonic() - started) * 1000, source, total,
                )
        raise SourceError(f"{source} {endpoint}: {last}")   # 도달 불가에 가깝지만 안전망
