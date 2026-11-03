"""접속 기록 가리기(#1201). 값은 모두 합성이다 — 실제 code·토큰·검색어를 쓰지 않는다."""

import logging
import socket
import threading
import time
import urllib.request

import pytest
import uvicorn
from fastapi import FastAPI
from sqlalchemy.exc import DBAPIError

from common import logguard
from common.errors import register_error_handlers

FAKE_CODE = "synthetic-code-7Qx"
FAKE_STATE = "synthetic-state-3Lm"
FAKE_TOKEN = "synthetic-invite-token-9Zk"
FAKE_QUERY = "synthetic-query-5Ab"
FAKE_PARAM = "synthetic-sql-param-1Pw"


@pytest.mark.parametrize("target,expected", [
    ("/auth/kakao/callback?code=C&state=S", "/auth/kakao/callback?[redacted]"),
    ("/places/search?q=Q&lat=37.5&lng=127.0", "/places/search?[redacted]"),
    ("/places/nearest?lat=37.5&lng=127.0", "/places/nearest?[redacted]"),
    ("/invites/TOKEN", "/invites/{token}"),
    ("/invites/TOKEN/accept", "/invites/{token}/accept"),
    ("/api/invites/TOKEN?x=1", "/api/invites/{token}?[redacted]"),   # --root-path /api
    ("/maps/abc/invites", "/maps/abc/invites"),                      # 목록은 토큰 자리가 없다
    ("/maps/abc/pins", "/maps/abc/pins"),
    ("/places/nearest", "/places/nearest"),
])
def test_mask_request_target(target, expected):
    assert logguard.mask_request_target(target) == expected


def test_install_is_idempotent():
    logguard.install()
    logguard.install()

    for name, kind in (("uvicorn.access", logguard.MaskRequestFilter), ("uvicorn.error", logguard.StripSqlParamsFilter),
                       ("common.errors", logguard.StripSqlParamsFilter)):
        assert sum(isinstance(f, kind) for f in logging.getLogger(name).filters) == 1


def _app() -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/auth/kakao/callback")
    def cb():
        return {"ok": True}

    @app.get("/invites/{token}")
    def invite(token: str):
        return {"ok": True}

    @app.get("/places/search")
    def search():
        return {"ok": True}

    @app.get("/boom")
    def boom():
        raise DBAPIError("SELECT 1 WHERE q = %(q)s", {"q": FAKE_PARAM}, Exception("driver"))

    return app


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        self.lines.append(self.format(record))


def test_real_uvicorn_logs_hide_query_token_and_sql_params():
    """실제 uvicorn 서버의 접근 로그와 오류 로그를 모아, 합성 값이 하나도 없는지 본다."""
    logguard.install()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    collect = _Collect()
    collect.setFormatter(logging.Formatter("%(name)s %(message)s"))
    loggers = [logging.getLogger(n) for n in ("uvicorn.access", "uvicorn.error", "common.errors")]
    for lg in loggers:
        lg.addHandler(collect)
    server = uvicorn.Server(uvicorn.Config(_app(), host="127.0.0.1", port=port, log_level="info", lifespan="off", log_config=None))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        base = f"http://127.0.0.1:{port}"
        for path in (f"/auth/kakao/callback?code={FAKE_CODE}&state={FAKE_STATE}", f"/invites/{FAKE_TOKEN}",
                     f"/places/search?q={FAKE_QUERY}", "/boom"):
            try:
                urllib.request.urlopen(base + path, timeout=5).read()
            except urllib.error.HTTPError:
                pass   # /boom은 500
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        for lg in loggers:
            lg.removeHandler(collect)

    text = "\n".join(collect.lines)
    for value in (FAKE_CODE, FAKE_STATE, FAKE_TOKEN, FAKE_QUERY, FAKE_PARAM):
        assert value not in text
    assert "GET /auth/kakao/callback?[redacted] HTTP/1.1" in text and "GET /invites/{token} HTTP/1.1" in text   # 템플릿·상태는 남는다
    assert " 500" in text and "DBAPIError" in text                                                            # 오류는 종류와 위치만 남는다
