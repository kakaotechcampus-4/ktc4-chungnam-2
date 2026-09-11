"""
공통 에러 응답 테스트.

제일 중요한 건 test_catalog_matches_docs다 — 이 파일의 진짜 실패 모드는 로직 버그가 아니라
`docs/errors.md`(정본)와 CATALOG가 조용히 갈라지는 것이다.
"""

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from common.errors import CATALOG, AppError, error_response, register_error_handlers

DOCS_ERRORS = Path(__file__).resolve().parents[3] / "docs" / "errors.md"

RAISABLE = sorted(code for code, (status, _) in CATALOG.items() if status >= 400)
NOT_RAISABLE = sorted(code for code, (status, _) in CATALOG.items() if status < 400)


class _Body(BaseModel):
    place_id: str


def _client(raise_server_exceptions: bool = True) -> TestClient:
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/raise/{code}")
    def _raise(code: str):
        raise AppError(code)

    @app.get("/raise-with-detail")
    def _raise_with_detail():
        raise AppError("NO_RESULTS", detail={"funnel": {"예산": 3, "영업시간": 1}})

    @app.post("/validate")
    def _validate(body: _Body):
        return {"place_id": body.place_id}

    @app.post("/method-only")
    def _method_only():
        return {}

    @app.get("/boom")
    def _boom():
        raise RuntimeError("secret-internal-detail")

    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_catalog_matches_docs():
    """errors.md 표의 코드·HTTP가 CATALOG와 정확히 일치해야 한다."""
    # encoding 필수 — 없으면 로케일 인코딩을 써서 Windows(cp949)에서 한글 문서 읽다 터진다
    text = DOCS_ERRORS.read_text(encoding="utf-8")
    rows = re.findall(r"^\|\s*`([A-Z_]+)`\s*\|\s*(\d+)", text, re.MULTILINE)
    documented = {code: int(status) for code, status in rows}

    assert documented, "errors.md 표를 한 줄도 못 읽었다 — 표 형식이 바뀌었는지 확인"
    assert RAISABLE and NOT_RAISABLE, "둘 중 하나가 비면 아래 parametrize가 0건으로 조용히 통과한다"
    assert set(documented) == set(CATALOG), "errors.md와 CATALOG의 코드 집합이 다르다"
    assert documented == {code: status for code, (status, _) in CATALOG.items()}, "코드별 HTTP가 다르다"


@pytest.mark.parametrize("code", RAISABLE)
def test_each_code_returns_error_envelope(code):
    response = _client().get(f"/raise/{code}")

    assert response.status_code == CATALOG[code][0]
    body = response.json()
    assert set(body) == {"code", "message"}, "detail이 없으면 키 자체가 빠져야 한다"
    assert body["code"] == code
    assert body["message"]


def test_detail_passes_through():
    body = _client().get("/raise-with-detail").json()

    assert body["code"] == "NO_RESULTS"
    assert body["detail"] == {"funnel": {"예산": 3, "영업시간": 1}}


@pytest.mark.parametrize("code", NOT_RAISABLE)
def test_200_codes_cannot_be_raised(code):
    """MAP_EMPTY·SHORTLIST_CATEGORY_EMPTY는 에러가 아니라 빈 배열 200이다."""
    with pytest.raises(ValueError):
        AppError(code)


def test_unknown_code_is_rejected():
    """errors.md에 없는 코드를 모듈이 즉석에서 만들 수 없어야 한다."""
    with pytest.raises(KeyError):
        AppError("PIN_TOO_SPICY")


def test_request_validation_error():
    response = _client().post("/validate", json={})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert body["detail"]["errors"]


def test_unknown_route():
    response = _client().get("/없는경로")

    assert response.status_code == 404
    assert response.json()["code"] == "NOT_FOUND"


def test_unhandled_exception_does_not_leak():
    response = _client(raise_server_exceptions=False).get("/boom")

    assert response.status_code == 500
    assert response.json()["code"] == "INTERNAL_ERROR"
    assert "secret-internal-detail" not in response.text


def test_error_response_also_rejects_200_codes():
    """AppError뿐 아니라 error_response()로도 200 코드를 에러 응답으로 못 만든다."""
    with pytest.raises(ValueError):
        error_response("MAP_EMPTY")


def test_405_keeps_allow_header():
    """봉투를 갈아끼우면서 원래 헤더를 잃지 않아야 한다 (401의 WWW-Authenticate도 같은 경로)."""
    response = _client().get("/method-only")

    assert response.status_code == 405
    assert "POST" in response.headers["allow"]
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_500_through_the_real_stack_has_cors_headers():
    """throwaway 앱이 아니라 main.asgi_app을 그대로 태운다 —
    500이 CORS 헤더 없이 나가면 브라우저 FE가 본문을 못 읽는다(회귀 방지).

    전역 app.router.routes를 건드리므로(진짜 asgi_app을 태우려면 진짜 라우트가 필요해서)
    스냅샷/복원 방식을 쓴다 — 경로 문자열로 걸러내는 방식은 등록 자체가 실패했을 때 아무 것도
    못 지우거나, 우연히 같은 경로의 다른 라우트를 지울 위험이 있다(2차 DeepSeek 재검수 지적).
    이 프로젝트는 pytest-xdist 등 병렬 실행 플러그인이 없어(requirements.txt에 없음, 확인됨)
    순차 실행을 전제해도 안전하다 — 병렬 실행 플러그인을 나중에 도입하면 이 테스트는 별도
    서브앱으로 격리해야 한다."""
    from main import app as fastapi_app, asgi_app

    original_routes = list(fastapi_app.router.routes)   # 전체 스냅샷 — 부분 필터링 안 함

    @fastapi_app.get("/__boom__")
    def _boom():
        raise RuntimeError("secret-internal-detail")

    origin = "http://localhost:5173"
    try:
        client = TestClient(asgi_app, raise_server_exceptions=False)
        response = client.get("/__boom__", headers={"Origin": origin})
        assert response.status_code == 500
        assert response.headers["access-control-allow-origin"] == origin
        assert response.headers["access-control-allow-credentials"] == "true"
        assert response.json()["code"] == "INTERNAL_ERROR"
        assert "secret-internal-detail" not in response.text
    finally:
        fastapi_app.router.routes = original_routes   # 등록이 실패했어도 항상 정확히 복원됨


def test_wildcard_origin_is_never_used_with_credentials():
    """ACAO:* + credentials는 브라우저가 거부한다 — 쿠키 인증이라 절대 쓰면 안 된다."""
    from main import asgi_app
    client = TestClient(asgi_app)
    r = client.get("/health", headers={"Origin": "http://localhost:5173"})
    assert r.headers.get("access-control-allow-origin") != "*"
    assert r.headers.get("vary") == "Origin"
