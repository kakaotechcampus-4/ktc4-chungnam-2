"""
auth.deps.get_current_user 단위 테스트 + 회귀 테스트 — 실제 PostgreSQL 필요(auth/tests/conftest.py의 db_session).
AUTH_MODE·개발용 스텁은 없다(#126) — 구현은 서명된 세션 쿠키를 검증하는 이것 하나다.
"""

import time
from datetime import datetime, timezone

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from auth import core
from auth.deps import get_current_user
from auth.models import User
from common.errors import AppError, register_error_handlers
from common.settings import settings


def test_resolver_missing_cookie_raises_unauthorized(db_session):
    with pytest.raises(AppError) as exc:
        get_current_user(session=None, db=db_session)
    assert exc.value.code == "UNAUTHORIZED"


def test_resolver_accepts_valid_signed_cookie_for_active_user(db_session):
    db_session.add(User(id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수"))
    db_session.flush()
    token = core.create_session_token("user_1", secret=settings.session_secret, issued_at=int(time.time()))

    user = get_current_user(session=token, db=db_session)

    assert user.user_id == "user_1"


def test_resolver_rejects_tampered_cookie(db_session):
    with pytest.raises(AppError) as exc:
        get_current_user(session="tampered.123.deadbeef", db=db_session)
    assert exc.value.code == "UNAUTHORIZED"


def test_resolver_rejects_valid_signature_for_withdrawn_user(db_session):
    """서명은 멀쩡해도(쿠키가 만료 전) 그 사이 탈퇴한 계정이면 즉시 막힌다 — 쿠키만 보고
    판정하지 않고 매번 DB를 재확인하는 이유(auth/deps.py 참고)."""
    db_session.add(
        User(
            id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수",
            deleted_at=datetime.now(timezone.utc),
        )
    )
    db_session.flush()
    token = core.create_session_token("user_1", secret=settings.session_secret, issued_at=int(time.time()))

    with pytest.raises(AppError) as exc:
        get_current_user(session=token, db=db_session)
    assert exc.value.code == "UNAUTHORIZED"


def test_resolver_rejects_token_issued_before_logout_but_accepts_new_one(db_session):
    now = int(time.time())
    db_session.add(
        User(
            id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수",
            sessions_valid_after=datetime.fromtimestamp(now - 5, tz=timezone.utc),
        )
    )
    db_session.flush()
    old = core.create_session_token("user_1", secret=settings.session_secret, issued_at=now - 10)
    new = core.create_session_token("user_1", secret=settings.session_secret, issued_at=now - 1)

    with pytest.raises(AppError) as exc:
        get_current_user(session=old, db=db_session)
    assert exc.value.code == "UNAUTHORIZED"
    assert get_current_user(session=new, db=db_session).user_id == "user_1"


def test_missing_cookie_via_http_returns_envelope():
    """common/errors.py의 앱 레벨 핸들러가 의존성 단계 예외도 잡는지 확인 —
    pins/deps.py의 예전 우회 이유가 더 이상 유효하지 않음을 증명하는 회귀 테스트.

    주의: 이 테스트는 throwaway FastAPI()에 핸들러를 다시 등록해서 확인한다 — 실제 main.py의
    등록 순서·asgi_app 배선이 맞는지는 증명하지 않는다. 지금은 "AppError가 의존성 단계에서
    앱 레벨 핸들러에 잡히는가"라는 좁은 질문에 답하는 게 목적이다. 실제 main.asgi_app 경로를
    타는 확인은 이제 auth/tests/test_router.py::test_missing_cookie_via_real_asgi_app_returns_envelope가
    한다(auth/for_Root.md "루트 확인·결정 필요" 3번 해소).
    """
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/protected", dependencies=[Depends(get_current_user)])
    def _protected():
        return {"ok": True}

    response = TestClient(app).get("/protected")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
