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
FAKE_LAT = "11.111111"   # 좌표 모양의 합성 값(#1155) — 실제 지도 좌표가 아니다
FAKE_LNG = "22.222222"
FAKE_PARAM = "synthetic-sql-param-1Pw"


@pytest.mark.parametrize("target,expected", [
    ("/auth/kakao/callback?code=C&state=S", "/auth/kakao/callback?[redacted]"),
    ("/places/search?q=Q&lat=37.5&lng=127.0", "/places/search?[redacted]"),
    ("/places/nearest?lat=37.5&lng=127.0", "/places/nearest?[redacted]"),
    ("/invites/TOKEN", "/invites/{token}"),
    ("/invites/TOKEN/accept", "/invites/{token}/accept"),
    ("/api/invites/TOKEN?x=1", "/api/invites/{token}?[redacted]"),   # --root-path /api
    ("/maps/abc/invites", "/maps/abc/invites"),                      # 목록은 토큰 자리가 없다
    ("/invites//TOKEN", "/invites//{token}"),                        # 슬래시가 겹쳐도
    ("/Invites/TOKEN/accept", "/Invites/{token}/accept"),            # 대소문자가 달라도
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

    @app.get("/places/nearest")
    def nearest():
        return {"ok": True}

    @app.get("/maps/{map_id}/ads")
    def ads(map_id: str):
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
                     f"/places/search?q={FAKE_QUERY}&lat={FAKE_LAT}&lng={FAKE_LNG}",
                     f"/places/nearest?lat={FAKE_LAT}&lng={FAKE_LNG}&category=cafe",
                     f"/maps/m1/ads?lat={FAKE_LAT}&lng={FAKE_LNG}&category=cafe", "/boom"):
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
    for value in (FAKE_CODE, FAKE_STATE, FAKE_TOKEN, FAKE_QUERY, FAKE_PARAM, FAKE_LAT, FAKE_LNG):
        assert value not in text
    assert "GET /auth/kakao/callback?[redacted] HTTP/1.1" in text and "GET /invites/{token} HTTP/1.1" in text   # 템플릿·상태는 남는다
    for path in ("/places/search", "/places/nearest", "/maps/m1/ads"):   # #1155: 검색어·좌표가 붙는 경로는 쿼리만 지워진다
        assert f"GET {path}?[redacted] HTTP/1.1" in text
    assert " 500" in text and "DBAPIError" in text                                                            # 오류는 종류와 위치만 남는다


def _sql_error():
    return DBAPIError("SELECT 1 WHERE q = %(q)s", {"q": FAKE_PARAM}, Exception("driver"))


def _record(exc: BaseException, name="pingo.x") -> logging.LogRecord:
    try:
        raise exc
    except BaseException:
        import sys
        return logging.LogRecord(name, logging.ERROR, "", 0, "failed", None, sys.exc_info())


def test_strip_sql_params_clears_exc_info_so_no_formatter_prints_the_original():
    rec = _record(_sql_error())

    logguard.StripSqlParamsFilter().filter(rec)

    assert rec.exc_info is None
    out = logging.Formatter("%(message)s").format(rec)
    assert FAKE_PARAM not in out and "DBAPIError" in out


def test_chain_walks_cause_context_and_exception_groups():
    inner = _sql_error()
    cause = RuntimeError("c")
    cause.__cause__ = inner
    ctx = RuntimeError("x")
    ctx.__context__ = inner
    assert inner in list(logguard._chain(cause)) and inner in list(logguard._chain(ctx))
    import builtins
    if hasattr(builtins, "BaseExceptionGroup"):   # 3.11+
        group = builtins.BaseExceptionGroup("g", [inner])
        assert inner in list(logguard._chain(group))
        assert logguard.StripSqlParamsFilter().filter(_record(group)) is True
    loop = RuntimeError("loop")
    loop.__cause__ = loop
    assert list(logguard._chain(loop)) == [loop]   # 순환해도 끝난다


def test_install_covers_app_loggers_through_root_handlers():
    """pingo.* 같은 앱 로거가 DB 오류를 찍는 경로도 덮는다 — 로거가 아니라 루트 핸들러의 필터가 건다."""
    import io
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(name)s %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        logguard.install()
        logguard.install()
        assert sum(isinstance(f, logguard.StripSqlParamsFilter) for f in handler.filters) == 1
        lg = logging.getLogger("pingo.test1201")
        try:
            raise _sql_error()
        except DBAPIError:
            lg.exception("db failed")
    finally:
        root.removeHandler(handler)
    assert FAKE_PARAM not in stream.getvalue() and "DBAPIError" in stream.getvalue()


def test_uvicorn_access_formatter_keeps_the_five_tuple_args():
    """uvicorn의 AccessFormatter는 args를 (client, method, path, http_version, status) 다섯으로 읽는다 — 구조를 깨지 않는다."""
    from uvicorn.logging import AccessFormatter, DefaultFormatter

    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
                            ("127.0.0.1:1", "GET", f"/invites/{FAKE_TOKEN}?code={FAKE_CODE}", "1.1", 200), None)

    logguard.MaskRequestFilter().filter(rec)

    assert isinstance(rec.args, tuple) and len(rec.args) == 5 and rec.args[0] == "127.0.0.1:1" and rec.args[3:] == ("1.1", 200)
    for formatter in (AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False),
                      DefaultFormatter("%(levelprefix)s %(message)s", use_colors=False)):
        out = formatter.format(rec)
        assert FAKE_TOKEN not in out and FAKE_CODE not in out and "/invites/{token}?[redacted]" in out


def test_places_logguard_keeps_old_names():
    from places import logguard as old

    assert old.StripQueryFilter is logguard.MaskRequestFilter and old.SENSITIVE_PATHS == ("/places/nearest",)
