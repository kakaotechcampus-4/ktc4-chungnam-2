"""auth/service.py 통합 테스트 — 실제 PostgreSQL 필요(conftest.py 참고).

카카오 HTTP 호출은 실제로 나가지 않는다 — service.httpx.post/get을 몬키패치한다
(requirements.txt에 respx 등 HTTP 모킹 라이브러리가 없어 표준 방식으로 대체).
"""

import pytest

from sqlalchemy import select

from auth import service
from auth.models import User, UserIdentity
from auth.testing import create_kakao_user
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


def _identities(db, user_id):
    return db.execute(
        select(UserIdentity.provider, UserIdentity.provider_user_id).where(UserIdentity.user_id == user_id)
    ).all()


def test_login_with_kakao_code_creates_new_user(db_session, monkeypatch):
    _mock_kakao_success(monkeypatch, kakao_id=42, nickname="철수")

    user = service.login_with_kakao_code(db_session, code="auth-code")

    assert _identities(db_session, user.id) == [("kakao", "42")]   # 사용자와 수단을 함께 만든다(#694)
    assert user.display_name == "철수"
    assert user.is_guest is False
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
    create_kakao_user(db_session, "user_1", display_name="철수")
    service.withdraw_user(db_session, user_id="user_1")

    with pytest.raises(AppError) as exc:
        service.get_active_user_or_401(db_session, user_id="user_1")
    assert exc.value.code == "UNAUTHORIZED"


def test_withdraw_user_sets_deleted_at(db_session):
    create_kakao_user(db_session, "user_1", display_name="철수")

    withdrawn = service.withdraw_user(db_session, user_id="user_1")

    assert withdrawn.deleted_at is not None


def test_withdraw_user_detaches_feedback_author_but_keeps_content(db_session):
    from feedback import service as feedback_service
    from feedback.models import Feedback

    create_kakao_user(db_session, "user_1", display_name="철수")
    row = feedback_service.submit(db_session, user_id="user_1", message="의견", category="idea", map_id=None)

    service.withdraw_user(db_session, user_id="user_1")

    db_session.expire_all()
    saved = db_session.get(Feedback, row.id)
    assert saved.user_id is None and saved.message == "의견"


def test_withdraw_user_locks_member_maps_before_anything_else(db_session, monkeypatch):
    create_kakao_user(db_session, "user_1", display_name="철수")
    calls = []
    monkeypatch.setattr(service.maps_api, "lock_member_maps", lambda db, user_id: calls.append(("lock", user_id)) or [])
    monkeypatch.setattr(service.maps_api, "transfer_or_delete_owned_maps", lambda db, user_id: calls.append(("transfer", user_id)))
    monkeypatch.setattr(service.pins_api, "delete_reactions_by_user", lambda db, user_id: calls.append(("reactions", user_id)))
    monkeypatch.setattr(service.recommend_api, "delete_evidence_lines_by_author", lambda db, user_id: calls.append(("evidence", user_id)))

    service.withdraw_user(db_session, user_id="user_1")

    assert [name for name, _ in calls] == ["lock", "transfer", "reactions", "evidence"]
    assert all(uid == "user_1" for _, uid in calls)


def test_withdraw_keeps_the_login_identity_so_the_account_stays_blocked(db_session):
    """탈퇴해도 수단은 남는다 — 같은 카카오 계정의 재로그인을 막는 근거다(#409, #694)."""
    create_kakao_user(db_session, "user_1", provider_user_id="pu1")

    service.withdraw_user(db_session, user_id="user_1")

    assert _identities(db_session, "user_1") == [("kakao", "pu1")]
    with pytest.raises(AppError):
        service.find_or_create_user(db_session, provider="kakao", provider_user_id="pu1", display_name="다시")


def test_withdraw_steps_are_also_merge_steps():
    """탈퇴에서 사용자 기록을 다루는 모듈은 게스트 합치기에서도 옮겨야 한다(#694). 한쪽 목록에만 모듈이 더해지면
    합친 뒤 게스트 때 기록이 안 보이거나(합치기 누락) 탈퇴 뒤에 남는다."""
    withdraw_modules = {name for name, _ in service.WITHDRAW_STEPS}
    merge_modules = {name for name, _ in service.MERGE_STEPS}
    assert withdraw_modules <= merge_modules, withdraw_modules - merge_modules


def test_withdraw_runs_every_step_in_order(db_session, monkeypatch):
    create_kakao_user(db_session, "user_1")
    calls = []
    monkeypatch.setattr(service, "WITHDRAW_STEPS", tuple(
        (name, lambda db, user_id, map_ids, name=name: calls.append((name, user_id, map_ids)))
        for name in ("maps", "pins", "agent")
    ))
    monkeypatch.setattr(service.maps_api, "lock_member_maps", lambda db, user_id: ["m1"])

    service.withdraw_user(db_session, user_id="user_1")

    assert calls == [("maps", "user_1", ["m1"]), ("pins", "user_1", ["m1"]), ("agent", "user_1", ["m1"])]


def test_revoke_sessions_sets_sessions_valid_after(db_session):
    create_kakao_user(db_session, "user_1", display_name="철수")

    service.revoke_sessions(db_session, user_id="user_1")
    db_session.expire_all()

    assert db_session.get(User, "user_1").sessions_valid_after is not None


def test_revoke_sessions_for_unknown_user_does_not_fail(db_session):
    service.revoke_sessions(db_session, user_id="nobody")


# ---- 첫 로그인 동시 요청(#126) ----

def _simulate_lost_race(monkeypatch):
    """두 요청이 거의 동시에 들어와 둘 다 "사용자가 없다"고 본 순간을 만든다 — 첫 조회만 None을 돌려주고,
    그 뒤(유일 제약 위반 후 재조회)는 실제 조회다."""
    real_find = service._find_user
    calls = {"n": 0}

    def find_once_empty(db, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(db, **kwargs)

    monkeypatch.setattr(service, "_find_user", find_once_empty)


def test_concurrent_first_login_returns_the_row_created_by_the_other_request(db_session, monkeypatch):
    winner = create_kakao_user(db_session, provider_user_id="777", display_name="먼저 온 요청")
    users_before = db_session.query(User).count()
    _simulate_lost_race(monkeypatch)

    row = service.find_or_create_user(db_session, provider="kakao", provider_user_id="777", display_name="나중 요청")

    assert row.id == winner.id
    assert row.display_name == "먼저 온 요청"   # 나중 요청이 덮어쓰지 않는다
    assert db_session.query(UserIdentity).filter_by(provider_user_id="777").count() == 1
    assert db_session.query(User).count() == users_before   # 세이브포인트와 함께 users 행도 되돌아갔다


def test_concurrent_first_login_still_rejects_withdrawn_account(db_session, monkeypatch):
    from datetime import datetime, timezone

    create_kakao_user(db_session, provider_user_id="778", display_name="x", deleted_at=datetime.now(timezone.utc))
    _simulate_lost_race(monkeypatch)

    with pytest.raises(AppError) as exc:
        service.find_or_create_user(db_session, provider="kakao", provider_user_id="778", display_name="x")
    assert exc.value.code == "UNAUTHORIZED"


def test_other_integrity_errors_are_not_swallowed(db_session):
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):   # NOT NULL 위반(23502) — 유일 제약 위반이 아니므로 그대로 올라온다
        service.find_or_create_user(db_session, provider="kakao", provider_user_id="779", display_name=None)


# ---- 카카오 응답 정리 (#315) — KeyError·500이 아니라 KakaoApiError(kakao_failed) ----

class _BadJson(_FakeResponse):
    def json(self):
        raise ValueError("not json")


@pytest.mark.parametrize("token_response, reason", [
    (_FakeResponse(200, {}), "missing_access_token"),
    (_FakeResponse(200, {"access_token": ""}), "missing_access_token"),
    (_FakeResponse(200, {"access_token": None}), "missing_access_token"),
    (_FakeResponse(200, ["not", "an", "object"]), "unexpected_shape"),
    (_BadJson(200, {}), "invalid_json"),
    (_FakeResponse(400, {"error": "invalid_grant"}), "http_status"),
])
def test_bad_token_response_is_kakao_api_error(db_session, monkeypatch, token_response, reason):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: token_response)

    with pytest.raises(service.KakaoApiError) as exc:
        service.login_with_kakao_code(db_session, code="auth-code")

    assert exc.value.code == "UNAUTHORIZED"
    assert exc.value.detail["reason"] == reason


def test_profile_without_id_is_kakao_api_error(db_session, monkeypatch):
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(200, {"access_token": "t"}))
    monkeypatch.setattr(service.httpx, "get", lambda url, **kw: _FakeResponse(200, {"kakao_account": {}}))

    with pytest.raises(service.KakaoApiError) as exc:
        service.login_with_kakao_code(db_session, code="auth-code")
    assert exc.value.detail["reason"] == "missing_user_id"


def test_network_error_is_kakao_api_error_and_hides_request_details(db_session, monkeypatch):
    import httpx

    def refuse(url, **kw):
        raise httpx.ConnectError("connect failed for code=auth-code")

    monkeypatch.setattr(service.httpx, "post", refuse)

    with pytest.raises(service.KakaoApiError) as exc:
        service.login_with_kakao_code(db_session, code="auth-code")
    assert exc.value.detail == {"reason": "ConnectError"}
    assert "auth-code" not in str(exc.value)


def test_withdrawn_account_is_not_a_kakao_api_error(db_session, monkeypatch):
    _mock_kakao_success(monkeypatch, kakao_id=98, nickname="영희")
    user = service.login_with_kakao_code(db_session, code="c")
    service.withdraw_user(db_session, user_id=user.id)

    with pytest.raises(AppError) as exc:
        service.login_with_kakao_code(db_session, code="c2")
    assert not isinstance(exc.value, service.KakaoApiError)
