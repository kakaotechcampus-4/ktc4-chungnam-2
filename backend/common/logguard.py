"""접속 기록(uvicorn 접근 로그)에 사용자 값이 남지 않게 한다(#473, #1201, 카카오 약관 #53).

uvicorn 접근 로그는 요청 줄(`GET /places/search?q=..&lat=.. HTTP/1.1`)을 그대로 찍는다. 앱 로거는 이 값을 찍지 않는다 —
여기서는 서버 프로세스가 대신 찍는 접근 로그를 막는다. 경로 템플릿·상태·시간은 남긴다.

- 쿼리스트링은 경로를 가리지 않고 모두 지운다. 경로별 목록을 두면 새 경로(auth 콜백의 code·state, 검색어, 좌표)가
  생길 때마다 빠뜨린다.
- 예외 로그: DB 오류(SQLAlchemy)의 문자열은 `[SQL: ..] [parameters: ..]`로 바인딩 값(사용자 입력)을 담는다. 그 예외가 걸린
  레코드는 메시지 없이 예외 종류와 호출 위치(traceback 줄)만 남긴다. Starlette은 500 응답을 만든 뒤 예외를 다시 던져
  uvicorn.error가 한 번 더 찍으므로 두 로거에 모두 붙인다.
- 초대 토큰(`/invites/{token}`, `/invites/{token}/accept`)은 경로 자리를 `{token}`으로 바꾼다. 토큰은 접근 권한이다.
"""

from __future__ import annotations

import logging
import re
import traceback

from sqlalchemy.exc import SQLAlchemyError

REDACTED_QUERY = "?[redacted]"
# 앞단 프록시 경로(--root-path /api)가 붙어 찍혀도 맞도록 앞을 고정하지 않는다(#168). 지도 초대 목록(`/maps/{id}/invites`)은 뒤에 세그먼트가 없어 걸리지 않는다.
_INVITE_TOKEN = re.compile(r"(/invites/)[^/?]+")


def mask_request_target(target: str) -> str:
    """요청 대상(경로+쿼리)에서 쿼리스트링과 초대 토큰을 뺀다."""
    path, sep, _ = target.partition("?")
    path = _INVITE_TOKEN.sub(r"\1{token}", path)
    return path + REDACTED_QUERY if sep else path


class MaskRequestFilter(logging.Filter):
    """uvicorn.access 레코드의 args = (client, method, full_path, http_version, status)의 full_path를 가린다."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            record.args = (*args[:2], mask_request_target(args[2]), *args[3:])
        return True


def _chain(exc: BaseException | None):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


class StripSqlParamsFilter(logging.Filter):
    """예외 체인에 DB 오류가 있으면 traceback의 메시지(SQL·매개변수)를 빼고 종류와 호출 위치만 남긴다."""

    def filter(self, record: logging.LogRecord) -> bool:
        info = record.exc_info
        if isinstance(info, tuple) and info[1] is not None and any(isinstance(e, SQLAlchemyError) for e in _chain(info[1])):
            kinds = " <- ".join(type(e).__name__ for e in _chain(info[1]))
            frames = "".join(traceback.format_tb(info[2]))
            record.exc_text = f"Traceback (메시지·SQL 매개변수 생략): {kinds}\n{frames}".rstrip()
        return True


def _add_once(logger_name: str, filter_type: type[logging.Filter]) -> None:
    target = logging.getLogger(logger_name)
    if not any(isinstance(f, filter_type) for f in target.filters):
        target.addFilter(filter_type())


def install() -> None:
    """여러 번 불러도 필터는 하나만 붙는다."""
    _add_once("uvicorn.access", MaskRequestFilter)
    _add_once("uvicorn.error", StripSqlParamsFilter)
    _add_once("common.errors", StripSqlParamsFilter)
