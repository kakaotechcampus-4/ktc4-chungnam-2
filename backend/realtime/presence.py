"""지도 접속 상태(#1551) — 그 지도의 전체 채널 SSE에 열린 연결이 하나라도 있는 구성원이 접속 중이다.
같은 사람의 탭·기기 여럿은 한 명으로 센다. 마지막 연결이 끊기고 GRACE 안에 다시 붙지 않으면 접속이 아니다
(새로고침·잠깐 끊김에 점이 깜박이지 않게).

프로세스 메모리만 쓴다 — 저장하지 않고 접속 기록도 남기지 않는다(docs/events.md 「접속 상태의 한계」).
시계는 주입한다(테스트가 sleep 없이 유예를 건너뛴다). 쓰는 쪽(SSE 제너레이터와 폴링 루프)은 이벤트 루프 스레드지만
읽는 쪽(`realtime.api.online_user_ids`, maps의 동기 라우트)은 스레드풀에서 불린다 — 그래서 모든 메서드를 락 하나로 감싼다.
임계 구역은 dict 몇 개를 만지는 정도라 루프가 막힐 걱정은 없다."""

import threading
import time
from typing import Callable

GRACE = 30.0   # 마지막 연결이 끊긴 뒤 접속으로 치는 시간(초)


class Presence:
    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._lock = threading.Lock()
        self._connections: dict[str, dict[str, int]] = {}   # map_id → user_id → 열린 연결 수
        self._grace_until: dict[str, dict[str, float]] = {}   # map_id → user_id → 유예 끝 시각

    def connect(self, map_id: str, user_id: str) -> bool:
        """연결 하나가 열렸다. 접속 아님 → 접속으로 바뀌었으면 True(알릴 변화), 이미 접속이었으면 False.
        유예 안에 다시 붙은 것은 접속이 끊긴 적이 없으므로 False다. 유예가 이미 끝났는데 expire가 아직 안 돈
        경우는 접속이 끊겼던 것이므로 True다."""
        with self._lock:
            users = self._connections.setdefault(map_id, {})
            if users.get(user_id, 0) > 0:
                users[user_id] += 1
                return False
            users[user_id] = 1
            until = self._drop_grace(map_id, user_id)
            return until is None or until <= self._clock()

    def disconnect(self, map_id: str, user_id: str) -> None:
        """연결 하나가 닫혔다. 마지막 연결이면 유예를 시작한다(바로 접속 아님으로 치지 않는다)."""
        with self._lock:
            users = self._connections.get(map_id)
            if not users or users.get(user_id, 0) <= 0:
                return
            users[user_id] -= 1
            if users[user_id] > 0:
                return
            del users[user_id]
            if not users:
                del self._connections[map_id]
            self._grace_until.setdefault(map_id, {})[user_id] = self._clock() + GRACE

    def forget(self, map_id: str, user_id: str | None = None) -> None:
        """구성원이 아니게 되어(나가기·탈퇴) 또는 지도가 사라져 연결이 닫힌 사람을 유예 없이 집계에서 뺀다.
        user_id가 None이면 그 지도 전체. 이벤트는 만들지 않는다 — 나간 사람의 `online:false`를 알릴 이유가 없다
        (member.left가 이미 갔다). 이 뒤에 닫히는 연결의 disconnect는 아무것도 하지 않는다."""
        with self._lock:
            for table in (self._connections, self._grace_until):
                users = table.get(map_id)
                if users is None:
                    continue
                if user_id is None:
                    del table[map_id]
                    continue
                users.pop(user_id, None)
                if not users:
                    del table[map_id]

    def expire(self) -> list[tuple[str, str]]:
        """유예가 끝난 (map_id, user_id)를 치우고 돌려준다 — 부르는 쪽이 `online=false`를 알린다.
        폴링 루프가 주기적으로 부른다(안 부르면 끊긴 사람이 유예 표에 쌓인다)."""
        with self._lock:
            now = self._clock()
            done = [(m, u) for m, users in self._grace_until.items() for u, until in users.items() if until <= now]
            for map_id, user_id in done:
                self._drop_grace(map_id, user_id)
            return done

    def online_user_ids(self, map_id: str) -> set[str]:
        """열린 연결이 있거나 유예 안에 있는 구성원. 유예가 끝났는데 아직 expire가 안 돈 사람은 뺀다."""
        with self._lock:
            now = self._clock()
            online = set(self._connections.get(map_id, ()))
            online.update(u for u, until in self._grace_until.get(map_id, {}).items() if until > now)
            return online

    def _drop_grace(self, map_id: str, user_id: str) -> float | None:
        """락을 잡은 채로 부른다."""
        users = self._grace_until.get(map_id)
        if users is None:
            return None
        until = users.pop(user_id, None)
        if not users:
            del self._grace_until[map_id]
        return until
