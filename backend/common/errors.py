"""
공통 에러 응답 — `{ code, message, detail }` (docs/api-spec.yaml `Error` 스키마).

코드 카탈로그의 정본은 `docs/errors.md`다. 이 파일의 CATALOG는 그 표를 그대로 옮긴
것이고, tests/test_errors.py가 둘이 갈라지지 않았는지 매번 대조한다.
새 코드가 필요하면 errors.md에 먼저 추가한다(루트 확인 후) — 여기부터 고치지 않는다.
"""

import logging
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

# code -> (HTTP status, 기본 message).
# message는 BE용 한 줄 요약이다. 화면 문구(기획안 6절 "아직 아무도 핀을 찍지 않았어요" 등)는
# FE 소유라 여기 넣지 않는다 — 필요하면 호출부에서 message를 덮어쓴다.
CATALOG: dict[str, tuple[int, str]] = {
    "MAP_EMPTY": (200, "핀이 아직 없습니다"),
    "NO_RESULTS": (404, "필터를 통과한 후보가 없습니다"),
    "NOT_READY": (409, "추천 준비가 덜 됐습니다"),
    "EVIDENCE_REQUIRED": (422, "사유가 필요합니다"),
    "PIN_DUPLICATE": (409, "이미 지도에 있는 장소입니다"),
    "AI_PIN_PRIVATE": (404, "비공개 AI 핀입니다"),
    "REGION_CONFLICT": (409, "두 조건을 동시에 만족하는 곳이 없습니다"),
    "RETRY_LIMIT": (429, "재시도 상한을 넘었습니다"),
    "RECOMMEND_FAILED": (500, "추천을 만들지 못했습니다"),
    "SHORTLIST_CATEGORY_EMPTY": (200, "이 분류에 확정된 곳이 없습니다"),
    "UNAUTHORIZED": (401, "인증이 필요합니다"),
    "FORBIDDEN": (403, "권한이 없습니다"),
    "IDEMPOTENCY_CONFLICT": (409, "같은 키로 다른 내용의 요청이 왔습니다"),
    "VALIDATION_ERROR": (422, "요청 형식이 올바르지 않습니다"),
    "NOT_FOUND": (404, "없는 경로이거나 없는 리소스입니다"),
    "INTERNAL_ERROR": (500, "서버 오류입니다"),
}


class AppError(Exception):
    """모듈이 던지는 유일한 에러 타입. code는 CATALOG(=errors.md)에 있는 것만 쓴다."""

    def __init__(self, code: str, message: str | None = None, detail: dict[str, Any] | None = None):
        status, default_message = CATALOG[code]  # 카탈로그에 없는 코드면 KeyError로 즉시 터진다
        if status < 400:
            raise ValueError(f"{code}는 200 응답용 코드다 — 에러로 던지지 않고 빈 배열을 반환한다")
        super().__init__(f"{code}: {message or default_message}")
        self.code = code
        self.status = status
        self.message = message or default_message
        self.detail = detail


def error_response(code: str, message: str | None = None, detail: dict[str, Any] | None = None) -> JSONResponse:
    """카탈로그 코드 하나를 `Error` 스키마 응답으로. detail은 없으면 키 자체를 뺀다(스키마상 선택)."""
    status, default_message = CATALOG[code]
    if status < 400:
        raise ValueError(f"{code}는 200 응답용 코드다 — 에러 응답으로 만들지 않는다")
    body: dict[str, Any] = {"code": code, "message": message or default_message}
    if detail is not None:
        body["detail"] = detail
    return JSONResponse(status_code=status, content=body)


def _code_for_http_status(status: int) -> str:
    """카탈로그 밖에서 올라온 HTTPException을 봉투에 맞추기 위한 매핑."""
    if status == 401:
        return "UNAUTHORIZED"
    if status == 403:
        return "FORBIDDEN"
    if status == 404:
        return "NOT_FOUND"
    if status < 500:
        return "VALIDATION_ERROR"  # 405·415 등 — 요청 자체가 잘못된 경우
    return "INTERNAL_ERROR"


def register_error_handlers(app) -> None:
    """FastAPI 앱의 모든 에러 응답을 `{ code, message, detail? }` 하나로 통일한다."""

    @app.exception_handler(AppError)
    async def _app_error(_request, exc: AppError):
        return error_response(exc.code, exc.message, exc.detail)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request, exc: RequestValidationError):
        return error_response("VALIDATION_ERROR", detail={"errors": jsonable_encoder(exc.errors())})

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_request, exc: StarletteHTTPException):
        code = _code_for_http_status(exc.status_code)
        # 상태코드는 FastAPI가 정한 값을 그대로 쓴다(405 등 카탈로그에 없는 값이 올 수 있다).
        # headers도 그대로 넘긴다 — 405의 Allow, 401의 WWW-Authenticate가 여기서 사라지면 안 된다.
        _, default_message = CATALOG[code]
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": code, "message": default_message},
            headers=exc.headers,
        )

    # ponytail: 이 핸들러는 ServerErrorMiddleware에서 돌아 CORSMiddleware 바깥이다 —
    # 500 응답에는 CORS 헤더가 안 붙어서 브라우저 FE는 본문을 못 읽는다(네트워크 에러로 보인다).
    # 고치려면 catch-all을 CORS보다 먼저 등록하는 미들웨어로 바꿔야 하는데,
    # BaseHTTPMiddleware가 SSE(#13) 스트리밍을 버퍼링해 깨뜨린다. 500이 잦아지면 그때 교환한다.
    @app.exception_handler(Exception)
    async def _unhandled(_request, exc: Exception):
        # 예외 내용은 로그에만 남긴다 — 응답에 넣으면 내부 정보가 그대로 나간다
        logger.exception("unhandled exception", exc_info=exc)
        return error_response("INTERNAL_ERROR")
