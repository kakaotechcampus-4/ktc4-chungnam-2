"""메모리 TTL 캐시 — 영구 저장이 아니다(#53 결정 전). ttl_s=0이면 아무것도 담지 않는다."""

from __future__ import annotations

import threading
import time
from typing import Callable, Generic, TypeVar

V = TypeVar("V")


class TTLCache(Generic[V]):
    def __init__(self, ttl_s: float, *, max_size: int = 2000, clock: Callable[[], float] = time.monotonic) -> None:
        self._ttl = ttl_s
        self._max = max_size
        self._clock = clock
        self._data: dict[str, tuple[float, V]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self._ttl > 0

    def get(self, key: str) -> V | None:
        if not self.enabled:
            return None
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, value = item
            if self._clock() >= expires:
                del self._data[key]
                return None
            return value

    def put(self, key: str, value: V) -> None:
        if not self.enabled:
            return
        with self._lock:
            if len(self._data) >= self._max and key not in self._data:
                now = self._clock()
                for k in [k for k, (exp, _) in self._data.items() if exp <= now]:
                    del self._data[k]
                if len(self._data) >= self._max:   # 여전히 가득이면 가장 오래된 것부터
                    del self._data[min(self._data, key=lambda k: self._data[k][0])]
            self._data[key] = (self._clock() + self._ttl, value)
