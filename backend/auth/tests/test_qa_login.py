"""스테이징 전용 QA 로그인 POST /auth/qa-login(#788, #789).

경로를 붙일지는 main.py가 설정을 보고 정한다. 그래서 설정 싱글턴을 staging·prod 값으로 바꿔 끼운 뒤 main.py를
별도 모듈로 다시 실행해 앱을 만든다(테스트 앱 `main.app`과 sys.modules["main"]은 그대로 둔다). lifespan은 돌리지 않는다.
"""

import dataclasses
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import common.settings
from auth import service
from auth.models import User, UserIdentity
from common.database import get_db_session, session_scope

MAIN_PY = Path(__file__).resolve().parents[2] / "main.py"
SECRET = "qa-secret-for-tests"
QA_LOGIN = "/auth/qa-login"
MAP_BODY = {"title": "QA", "start_date": "2026-11-01", "end_date": "2026-11-02"}


def _strict_settings(environment: str, *, qa_login_secret: str):
    """prod와 같은 기동 가드를 통과하는 설정. 세션 비밀값도 기본값이 아니어야 한다."""
    return dataclasses.replace(
        common.settings.settings,
        environment=environment,
        qa_login_secret=qa_login_secret,
        session_secret="staging-session-secret",
        places_mode="real",
        llm_mode="real",
        cors_allow_origins=("https://staging.pingo.example",),
        cors_allow_origin_regex=None,
        frontend_base_url="https://staging.pingo.example",
        kakao_client_id="kid", kakao_client_secret="ksecret", kakao_redirect_uri="https://staging.pingo.example/cb",
        elice_ml_api_base_url="https://ml.example", elice_ml_api_key="elice-key",   # 실제 모드의 외부 키(#810)
    )


@pytest.fixture()
def build_app(monkeypatch, db_session):
    """설정을 받아 그 설정으로 만든 앱의 TestClient를 돌려준다."""
    original = common.settings.settings

    def _build(new_settings):
        # `from common.settings import settings`로 싱글턴을 들고 있는 모든 모듈을 같이 바꾼다(세션 쿠키 서명과 검증이 같은 값을 봐야 한다)
        for module in list(sys.modules.values()):
            if getattr(module, "settings", None) is original:
                monkeypatch.setattr(module, "settings", new_settings)
        spec = importlib.util.spec_from_file_location(f"main_{new_settings.environment}_for_test", MAIN_PY)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        def _override_get_db_session():
            with session_scope(db_session) as s:
                yield s

        module.app.dependency_overrides[get_db_session] = _override_get_db_session
        return TestClient(module.app)

    return _build


@pytest.fixture()
def staging(build_app):
    return build_app(_strict_settings("staging", qa_login_secret=SECRET))


def _qa_login(client, *, secret=SECRET, body=None):
    headers = {} if secret is None else {"X-QA-Login-Secret": secret}
    return client.post(QA_LOGIN, json=body if body is not None else {"display_name": "QA 사용자"}, headers=headers)


def test_right_secret_creates_a_non_guest_user_who_can_make_a_map(staging, db_session):
    r = _qa_login(staging, body={"display_name": "  QA 사용자  "})

    assert r.status_code == 201
    user = r.json()
    assert user["display_name"] == "QA 사용자" and user["is_guest"] is False
    assert "session" in r.cookies
    identity = db_session.execute(select(UserIdentity).where(UserIdentity.user_id == user["id"])).scalar_one()
    assert identity.provider == "qa"

    me = staging.get("/auth/me")
    assert me.status_code == 200
    assert me.json() == {"id": user["id"], "display_name": "QA 사용자", "is_guest": False}
    assert staging.post("/maps", json=MAP_BODY).status_code == 201


def test_each_call_makes_a_new_user(staging):
    first = _qa_login(staging).json()["id"]
    second = _qa_login(staging).json()["id"]

    assert first != second


@pytest.mark.parametrize("secret", [None, "", "wrong", "비밀값".encode()])   # ASCII 밖의 글자도 500이 아니라 403
def test_wrong_or_missing_secret_is_403(staging, db_session, secret):
    before = db_session.execute(select(User.id)).scalars().all()

    r = _qa_login(staging, secret=secret)

    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"
    assert "session" not in r.cookies
    assert db_session.execute(select(User.id)).scalars().all() == before


def test_wrong_secret_is_403_even_with_a_bad_body(staging):
    """비밀값 확인이 본문 검증보다 먼저다 — 비밀값 없이 본문 모양을 알아낼 수 없다."""
    assert _qa_login(staging, secret="wrong", body={"display_name": ""}).status_code == 403


@pytest.mark.parametrize("body", [{"display_name": ""}, {"display_name": "   "}, {"display_name": "가" * 51}, {},
                                  {"display_name": "QA", "is_guest": True}])
def test_invalid_body_is_422(staging, body):
    r = _qa_login(staging, body=body)

    assert r.status_code == 422
    assert r.json()["code"] == "VALIDATION_ERROR"


def test_fifty_char_name_is_accepted(staging):
    assert _qa_login(staging, body={"display_name": "가" * 50}).status_code == 201


def test_secret_is_not_logged(staging, caplog):
    with caplog.at_level("DEBUG"):
        _qa_login(staging)
        _qa_login(staging, secret="wrong-secret-value")

    assert SECRET not in caplog.text and "wrong-secret-value" not in caplog.text


def test_qa_user_withdraws_like_a_kakao_user(staging, db_session):
    """탈퇴는 provider를 보지 않는다 — 사용자는 soft delete, 로그인 수단은 남는다(#409)."""
    user_id = _qa_login(staging).json()["id"]

    assert staging.post("/auth/withdraw").status_code == 204

    assert db_session.get(User, user_id).deleted_at is not None
    assert db_session.execute(select(UserIdentity).where(UserIdentity.user_id == user_id)).scalar_one().provider == "qa"


def test_qa_session_is_not_treated_as_a_guest_when_starting_kakao_login(staging, db_session):
    """게스트 합치기는 로그인 수단이 없는 사용자만 대상이다 — qa 사용자의 세션은 카카오 사용자처럼 보통 로그인이 된다."""
    _qa_login(staging)

    assert service.live_guest_id_for_session(db_session, staging.cookies["session"]) is None


# ---- 경로가 없는 앱 ----


def test_test_app_has_no_qa_login(app_client):
    assert _qa_login(app_client).status_code == 404


def test_prod_app_has_no_qa_login(build_app):
    client = build_app(_strict_settings("prod", qa_login_secret=""))

    assert _qa_login(client).status_code == 404


def test_staging_app_without_secret_has_no_qa_login(build_app):
    client = build_app(_strict_settings("staging", qa_login_secret=""))

    assert _qa_login(client, secret="").status_code == 404
