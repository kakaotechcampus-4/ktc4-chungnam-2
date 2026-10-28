"""누른 좌표가 로그에 남지 않게 한다(#473, 카카오 약관 #53).

uvicorn 접근 로그는 요청 줄(`GET /places/nearest?lat=..&lng=.. HTTP/1.1`)을 그대로 찍는다. 이 경로의 쿼리스트링만 지운다.
앱 로거는 이 값을 찍지 않는다 — 여기서는 서버 프로세스가 대신 찍는 접근 로그를 막는다.
"""

from __future__ import annotations

import logging

SENSITIVE_PATHS = ("/places/nearest",)


class StripQueryFilter(logging.Filter):
    """uvicorn.access 레코드의 args = (client, method, full_path, http_version, status)에서 민감 경로의 쿼리를 뺀다."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path, sep, _ = args[2].partition("?")
            # 앞단 프록시 경로(--root-path /api)가 붙어 찍히므로 끝으로 맞춘다(#168)
            if sep and path.rstrip("/").endswith(SENSITIVE_PATHS):
                record.args = (*args[:2], path + "?[redacted]", *args[3:])
        return True


def install() -> None:
    """여러 번 불러도 필터는 하나만 붙는다."""
    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, StripQueryFilter) for f in access.filters):
        access.addFilter(StripQueryFilter())
