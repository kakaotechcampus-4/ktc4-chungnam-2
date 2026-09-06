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

from common.errors import CATALOG, AppError, register_error_handlers

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

    @app.get("/boom")
    def _boom():
        raise RuntimeError("secret-internal-detail")

    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_catalog_matches_docs():
    """errors.md 표의 코드·HTTP가 CATALOG와 정확히 일치해야 한다."""
    rows = re.findall(r"^\|\s*`([A-Z_]+)`\s*\|\s*(\d+)", DOCS_ERRORS.read_text(), re.MULTILINE)
    documented = {code: int(status) for code, status in rows}

    assert documented, "errors.md 표를 한 줄도 못 읽었다 — 표 형식이 바뀌었는지 확인"
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
