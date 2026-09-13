"""
auth.deps.get_current_user 단위 테스트 + 회귀 테스트.

쿠키 "잘못됨" 케이스는 지금 테스트하지 않는다 — 지금 스텁은 비어있지 않은 어떤 문자열도
유효한 것으로 받아들이므로(#4 전까지 검증 자체가 없음) "잘못된 쿠키"라는 상태가 아직 존재하지
않는다. #4가 실제 세션 검증을 구현하면 그때 이 케이스를 추가한다.
"""

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth.deps import get_current_user
from common.errors import AppError, register_error_handlers


def test_missing_cookie_raises_unauthorized():
    with pytest.raises(AppError) as exc:
        get_current_user(session=None)
    assert exc.value.code == "UNAUTHORIZED"


def test_present_cookie_becomes_user_id():
    user = get_current_user(session="user_42")
    assert user.user_id == "user_42"


def test_missing_cookie_via_http_returns_envelope():
    """common/errors.py의 앱 레벨 핸들러가 의존성 단계 예외도 잡는지 확인 —
    pins/deps.py의 예전 우회 이유가 더 이상 유효하지 않음을 증명하는 회귀 테스트.

    주의: 이 테스트는 throwaway FastAPI()에 핸들러를 다시 등록해서 확인한다 — 실제 main.py의
    등록 순서·asgi_app 배선이 맞는지는 증명하지 않는다. 지금은 "AppError가 의존성 단계에서
    앱 레벨 핸들러에 잡히는가"라는 좁은 질문에 답하는 게 목적이다. 실제 main.asgi_app 경로를
    타는 확인은 pins가 이 의존성을 라우터에 걸고 나면(pins/mentor-review-plan.md) 그 모듈의
    통합 테스트에서 이어서 검증한다.
    """
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/protected", dependencies=[Depends(get_current_user)])
    def _protected():
        return {"ok": True}

    response = TestClient(app).get("/protected")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
