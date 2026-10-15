"""사용자당 슬라이딩 윈도 호출 상한(인메모리). 프로세스 재시작 시 초기화되고, 인스턴스가 여러 개면 각자 센다."""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable

_PRUNE_AT = 10_000   # 키가 이만큼 쌓이면 오래된 키를 정리한다


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_s: float = 60.0, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = limit
        self._window = window_s
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        """허용이면 이번 호출을 세고 True. 상한을 넘으면 세지 않고 False. limit<=0이면 항상 True."""
        if self._limit <= 0:
            return True
        now = self._clock()
        with self._lock:
            if len(self._hits) >= _PRUNE_AT:
                self._prune(now)
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= self._window:
                hits.popleft()
            if len(hits) >= self._limit:
                return False
            hits.append(now)
            return True

    def _prune(self, now: float) -> None:
        for k in [k for k, h in self._hits.items() if not h or now - h[-1] >= self._window]:
            del self._hits[k]
