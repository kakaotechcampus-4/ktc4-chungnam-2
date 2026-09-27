"""auth/service.py 통합 테스트 — 실제 PostgreSQL 필요(conftest.py 참고).

카카오 HTTP 호출은 실제로 나가지 않는다 — service.httpx.post/get을 몬키패치한다
(requirements.txt에 respx 등 HTTP 모킹 라이브러리가 없어 표준 방식으로 대체).
"""

import pytest

from auth import service
from auth.models import User
from common.errors import AppError


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict):
        self.status_code = status_code
        self._json_body = json_body

    def json(self):
        return self._json_body


def _mock_kakao_success(monkeypatch, *, kakao_id=42, nickname="철수"):
    def fake_post(url, **kwargs):
        assert url == service.KAKAO_TOKEN_URL
        return _FakeResponse(200, {"access_token": "fake-token"})

    def fake_get(url, **kwargs):
        assert url == service.KAKAO_USERINFO_URL
        assert kwargs["headers"]["Authorization"] == "Bearer fake-token"
        return _FakeResponse(200, {"id": kakao_id, "kakao_account": {"profile": {"nickname": nickname}}})

    monkeypatch.setattr(service.httpx, "post", fake_post)
    monkeypatch.setattr(service.httpx, "get", fake_get)


def test_login_with_kakao_code_creates_new_user(db_session, monkeypatch):
    _mock_kakao_success(monkeypatch, kakao_id=42, nickname="철수")

    user = service.login_with_kakao_code(db_session, code="auth-code")

    assert user.provider == "kakao"
    assert user.provider_user_id == "42"
    assert user.display_name == "철수"
    assert user.deleted_at is None


def test_login_with_kakao_code_reuses_existing_user(db_session, monkeypatch):
    _mock_kakao_success(monkeypatch, kakao_id=42, nickname="철수")
    first = service.login_with_kakao_code(db_session, code="auth-code-1")

    _mock_kakao_success(monkeypatch, kakao_id=42, nickname="철수(닉네임 변경 안 반영)")
    second = service.login_with_kakao_code(db_session, code="auth-code-2")

    assert second.id == first.id
    # 재로그인 시 닉네임을 덮어쓰지 않는다 — find_or_create_user는 기존 행을 그대로 반환한다.
    assert second.display_name == "철수"


def test_login_fails_loudly_when_kakao_token_exchange_fails(db_session, monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse(400, {"error": "invalid_grant"})

    monkeypatch.setattr(service.httpx, "post", fake_post)

    with pytest.raises(AppError) as exc:
        service.login_with_kakao_code(db_session, code="bad-code")
    assert exc.value.code == "UNAUTHORIZED"


def test_login_fails_loudly_when_kakao_userinfo_fails(db_session, monkeypatch):
    def fake_post(url, **kwargs):
        return _FakeResponse(200, {"access_token": "fake-token"})

    def fake_get(url, **kwargs):
        return _FakeResponse(401, {"error": "invalid_token"})

    monkeypatch.setattr(service.httpx, "post", fake_post)
    monkeypatch.setattr(service.httpx, "get", fake_get)

    with pytest.raises(AppError) as exc:
        service.login_with_kakao_code(db_session, code="auth-code")
    assert exc.value.code == "UNAUTHORIZED"


def test_withdrawn_user_cannot_log_in_again(db_session, monkeypatch):
    _mock_kakao_success(monkeypatch, kakao_id=99, nickname="영희")
    user = service.login_with_kakao_code(db_session, code="auth-code")
    service.withdraw_user(db_session, user_id=user.id)

    with pytest.raises(AppError) as exc:
        service.login_with_kakao_code(db_session, code="auth-code-again")
    assert exc.value.code == "UNAUTHORIZED"


def test_get_active_user_or_401_rejects_unknown_user(db_session):
    with pytest.raises(AppError) as exc:
        service.get_active_user_or_401(db_session, user_id="no-such-user")
    assert exc.value.code == "UNAUTHORIZED"


def test_get_active_user_or_401_rejects_withdrawn_user(db_session):
    row = User(id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수")
    db_session.add(row)
    db_session.flush()
    service.withdraw_user(db_session, user_id="user_1")

    with pytest.raises(AppError) as exc:
        service.get_active_user_or_401(db_session, user_id="user_1")
    assert exc.value.code == "UNAUTHORIZED"


def test_withdraw_user_sets_deleted_at(db_session):
    row = User(id="user_1", provider="kakao", provider_user_id="pu1", display_name="철수")
    db_session.add(row)
    db_session.flush()

    withdrawn = service.withdraw_user(db_session, user_id="user_1")

    assert withdrawn.deleted_at is not None
