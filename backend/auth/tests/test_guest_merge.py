"""게스트 → 카카오 전환 통합 테스트(#560, #694) — 실제 PostgreSQL 필요(conftest.py 참고), main.app을 그대로 태운다.

처음 쓰는 카카오 계정이면 게스트 행에 수단을 붙이고(다른 모듈은 부르지 않는다), 이미 쓰던 카카오 계정이면 기록을 합친다.
합치기의 모듈 단계는 대역(MERGE_STEPS 교체)으로 검증한다. 실제 모듈을 태우는 끝단은 integration/test_guest_claim_e2e.py.
카카오 HTTP만 몬키패치한다.
"""

import time
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from auth import core, service
from auth.models import User, UserIdentity
from auth.testing import create_guest, create_kakao_user, session_cookie
from auth.tests.test_router import (  # noqa: F401 — kakao_configured는 픽스처
    _callback, _has_session_cookie, _is_cleared, _login_error, _mock_kakao_login, _seed_user, _start_login,
    kakao_configured, LOGIN_URL,
)
from auth.tests.test_service import _FakeResponse
from common.settings import settings

STEP_NAMES = ["maps", "pins", "recommend", "shortlist", "notifications", "feedback", "agent"]
KAKAO_ID = "kakao_k1"   # _seed_user(user_id="k1")의 카카오 사용자 id


def _seed_guest(db_session, user_id="g1", display_name="손님", **columns):
    return create_guest(db_session, user_id, display_name=display_name, **columns)


def _recording_steps(monkeypatch, *, fail_at=None, on_step=None):
    """모듈 api 대역 — 부른 순서와 인자를 기록한다. fail_at 단계는 예외를 던진다."""
    calls = []

    def make(name):
        def reassign_user(db, *, from_user_id, to_user_id):
            calls.append((name, from_user_id, to_user_id))
            if on_step:
                on_step(name, db, from_user_id)
            if name == fail_at:
                raise RuntimeError("secret detail that must not be logged")
        return SimpleNamespace(reassign_user=reassign_user)

    monkeypatch.setattr(service, "MERGE_STEPS", tuple((n, make(n)) for n in STEP_NAMES))
    return calls


def _identities(db_session, provider_user_id):
    return db_session.execute(
        select(UserIdentity.user_id).where(UserIdentity.provider == "kakao", UserIdentity.provider_user_id == provider_user_id)
    ).scalars().all()


def _state_cookie_value(client) -> str:
    return next(c.value for c in client.cookies.jar if c.name == "kakao_oauth_state")


def _start_login_as(client, user_id) -> str:
    """세션 쿠키를 들고 로그인 시작 — 카카오로 보낸 state를 돌려준다."""
    resp = client.get("/auth/kakao/login", cookies=session_cookie(user_id), follow_redirects=False)
    assert resp.status_code == 302, resp.text
    return parse_qs(urlparse(resp.headers["location"]).query)["state"][0]


def _guest_merged(resp) -> str | None:
    return parse_qs(urlparse(resp.headers["location"]).query).get("guest_merged", [None])[0]


def _callback_with_signed_state(client, cookie_value):
    """서버가 시작한 적 없는 조합의 state 쿠키로 콜백을 호출한다(쿠키의 state 값은 "st")."""
    client.cookies.clear()
    client.cookies.set("kakao_oauth_state", cookie_value, path="/")
    return _callback(client, code="auth-code", state="st")


def _signed_state(guest_user_id) -> str:
    return core.create_state_cookie_value(
        "st", secret=settings.session_secret, issued_at=int(time.time()), guest_user_id=guest_user_id,
    )


def _stale_first_lookup(monkeypatch):
    """겹친 요청이 "그 카카오 수단이 아직 없다"고 본 순간을 만든다 — 첫 조회만 None, 그 뒤는 실제 조회."""
    real_find = service._find_user
    calls = {"n": 0}

    def find_once_empty(db, **kwargs):
        calls["n"] += 1
        return None if calls["n"] == 1 else real_find(db, **kwargs)

    monkeypatch.setattr(service, "_find_user", find_once_empty)


def _claim(db_session, guest_user_id, provider_user_id="7"):
    return service.claim_guest(
        db_session, guest_user_id=guest_user_id, provider="kakao", provider_user_id=provider_user_id, display_name="민수",
    )


# ---- 로그인 시작: state 쿠키에 게스트 id ----

def test_login_from_a_guest_session_puts_the_guest_id_in_the_state_cookie(app_client, db_session, kakao_configured):
    _seed_guest(db_session, "g1")
    state = _start_login_as(app_client, "g1")
    claims = core.parse_state(_state_cookie_value(app_client), state, secret=settings.session_secret, now=int(time.time()))
    assert claims == core.StateClaims("g1")


@pytest.mark.parametrize("session", ["none", "kakao_user", "garbage", "unknown_user", "withdrawn_guest", "logged_out_guest"])
def test_login_without_a_live_guest_session_carries_no_guest_id(app_client, db_session, kakao_configured, session):
    _seed_user(db_session, user_id="k1")
    _seed_guest(db_session, "gw", deleted_at=datetime.now(timezone.utc))
    _seed_guest(db_session, "go", sessions_valid_after=datetime.now(timezone.utc))
    cookies = {
        "none": {}, "kakao_user": session_cookie("k1"), "garbage": {"session": "x.y.z"},
        "unknown_user": session_cookie("nobody"), "withdrawn_guest": session_cookie("gw"),
        "logged_out_guest": session_cookie("go"),
    }[session]
    resp = app_client.get("/auth/kakao/login", cookies=cookies, follow_redirects=False)
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    claims = core.parse_state(_state_cookie_value(app_client), state, secret=settings.session_secret, now=int(time.time()))
    assert claims == core.StateClaims(None)


# ---- 콜백: 처음 쓰는 카카오 계정 → 게스트 행에 수단을 붙인다(#694) ----

def test_first_kakao_login_attaches_the_identity_to_the_guest(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch, kakao_id=7, nickname="민수")
    _seed_guest(db_session, "g1", display_name="손님", guest_invite_token="tok")
    old_cookie = session_cookie("g1")
    calls = _recording_steps(monkeypatch)
    state = _start_login_as(app_client, "g1")

    resp = _callback(app_client, code="auth-code", state=state)

    assert _guest_merged(resp) == "true" and _login_error(resp) is None
    assert calls == []   # 다른 모듈은 부르지 않는다
    db_session.expire_all()
    guest = db_session.get(User, "g1")
    assert _identities(db_session, "7") == ["g1"]
    assert (guest.display_name, guest.guest_invite_token, guest.deleted_at, guest.is_guest) == ("손님", None, None, False)
    assert db_session.execute(select(User)).scalars().all() == [guest]   # 새 사용자를 만들지 않았다
    assert _has_session_cookie(resp) and _is_cleared(resp, "kakao_oauth_state")
    me = app_client.get("/auth/me")
    assert me.json() == {"id": "g1", "display_name": "손님", "is_guest": False}
    # 같은 사용자라 게스트 때 받은 세션도 그대로 통한다
    assert app_client.get("/auth/me", cookies=old_cookie).json()["is_guest"] is False


def test_unexpected_attach_failure_logs_in_with_a_new_account_and_keeps_the_guest(
    app_client, db_session, monkeypatch, kakao_configured, caplog,
):
    _mock_kakao_login(monkeypatch, kakao_id=7)
    _seed_guest(db_session, "g1")

    def boom(db, **kwargs):
        raise RuntimeError("secret detail that must not be logged")

    monkeypatch.setattr(service, "_attach_identity_to_guest", boom)
    state = _start_login_as(app_client, "g1")

    with caplog.at_level("ERROR"):
        resp = _callback(app_client, code="auth-code", state=state)

    assert _guest_merged(resp) == "false" and _login_error(resp) is None and _has_session_cookie(resp)
    kakao_users = _identities(db_session, "7")
    assert len(kakao_users) == 1 and kakao_users != ["g1"]
    guest = db_session.get(User, "g1")
    assert guest.deleted_at is None and guest.is_guest is True
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged and "secret detail" not in logged


def test_overlapping_callbacks_for_the_same_guest_attach_once(db_session, monkeypatch):
    """같은 게스트로 겹친 콜백 — 뒤 요청은 잠금을 기다린 뒤 수단이 이미 붙은 것을 보고 같은 사용자로 로그인한다."""
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    first = _claim(db_session, "g1")
    _stale_first_lookup(monkeypatch)   # 뒤 요청은 앞 요청이 붙이기 전에 수단을 찾아봤다

    second = _claim(db_session, "g1")

    assert [(u.id, merged) for u, merged in (first, second)] == [("g1", True), ("g1", True)]
    assert _identities(db_session, "7") == ["g1"] and calls == []
    assert db_session.get(User, "g1").deleted_at is None


def test_a_later_callback_for_an_already_attached_guest_is_the_same_user(db_session, monkeypatch):
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    _claim(db_session, "g1")

    user, merged = _claim(db_session, "g1")

    assert (user.id, merged) == ("g1", True) and calls == []


def test_same_kakao_attached_to_two_guests_at_once_merges_the_later_guest(db_session, monkeypatch):
    """같은 카카오가 두 게스트에 동시에 붙으면 유일 제약이 뒤 요청을 막고, 뒤 요청은 합치기로 간다."""
    _seed_guest(db_session, "g1")
    _seed_guest(db_session, "g2")
    calls = _recording_steps(monkeypatch)
    assert _claim(db_session, "g1")[1] is True
    _stale_first_lookup(monkeypatch)

    user, merged = _claim(db_session, "g2")

    assert (user.id, merged) == ("g1", True)
    assert _identities(db_session, "7") == ["g1"]
    assert calls == [(name, "g2", "g1") for name in STEP_NAMES]
    assert db_session.get(User, "g2").deleted_at is not None
    assert db_session.get(User, "g1").deleted_at is None


# ---- 콜백: 이미 쓰던 카카오 계정 → 합치기 ----

def test_guest_login_with_an_existing_kakao_account_merges_records(app_client, db_session, monkeypatch, kakao_configured):
    _seed_user(db_session, user_id="k1", display_name="철수")
    _mock_kakao_login(monkeypatch, kakao_id=KAKAO_ID, nickname="민수")
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    state = _start_login_as(app_client, "g1")

    resp = _callback(app_client, code="auth-code", state=state)

    assert _guest_merged(resp) == "true"
    assert _login_error(resp) is None
    assert calls == [(name, "g1", "k1") for name in STEP_NAMES]
    assert db_session.get(User, "g1").deleted_at is not None
    assert _identities(db_session, KAKAO_ID) == ["k1"]
    assert _has_session_cookie(resp) and _is_cleared(resp, "kakao_oauth_state")
    me = app_client.get("/auth/me")   # 응답의 세션 쿠키가 카카오 계정이다. 이름은 그 계정 것
    assert me.json() == {"id": "k1", "display_name": "철수", "is_guest": False}


def test_failed_merge_keeps_guest_and_rolls_back_but_login_succeeds(app_client, db_session, monkeypatch, kakao_configured, caplog):
    _seed_user(db_session, user_id="k1")
    _mock_kakao_login(monkeypatch, kakao_id=KAKAO_ID)
    _seed_guest(db_session, "g1", display_name="손님")

    def touch_guest(name, db, from_user_id):
        if name == "maps":   # 앞 단계의 쓰기 — 뒤 단계 실패로 같이 되돌아가야 한다
            db.get(User, from_user_id).display_name = "옮기다 만 이름"
            db.flush()

    _recording_steps(monkeypatch, fail_at="recommend", on_step=touch_guest)
    state = _start_login_as(app_client, "g1")

    with caplog.at_level("ERROR"):
        resp = _callback(app_client, code="auth-code", state=state)

    assert _guest_merged(resp) == "false"
    assert _login_error(resp) is None
    assert _has_session_cookie(resp)   # 카카오 로그인은 성공이다
    guest = db_session.get(User, "g1")
    assert guest.deleted_at is None and guest.display_name == "손님" and guest.is_guest is True
    logged = " ".join(r.getMessage() for r in caplog.records)
    assert "step=recommend" in logged and "RuntimeError" in logged
    assert "secret detail" not in logged


def test_module_without_reassign_user_fails_the_merge_instead_of_deleting_the_guest(app_client, db_session, monkeypatch, kakao_configured):
    """reassign_user가 없는 모듈이 있으면 일부만 옮긴 채 게스트를 지우지 않는다."""
    _seed_user(db_session, user_id="k1")
    _mock_kakao_login(monkeypatch, kakao_id=KAKAO_ID)
    _seed_guest(db_session, "g1")
    monkeypatch.setattr(service, "MERGE_STEPS", (("maps", SimpleNamespace()),))
    state = _start_login_as(app_client, "g1")

    resp = _callback(app_client, code="auth-code", state=state)

    assert _guest_merged(resp) == "false"
    assert db_session.get(User, "g1").deleted_at is None


def test_guest_login_into_a_withdrawn_kakao_account_is_rejected_and_keeps_the_guest(
    app_client, db_session, monkeypatch, kakao_configured,
):
    """탈퇴한 카카오 계정은 게스트가 시작해도 지금처럼 막는다(#409) — 붙이지도 합치지도 않는다."""
    create_kakao_user(db_session, "kw", provider_user_id="77", deleted_at=datetime.now(timezone.utc))
    _mock_kakao_login(monkeypatch, kakao_id=77)
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)

    resp = _callback(app_client, code="auth-code", state=_start_login_as(app_client, "g1"))

    assert _login_error(resp) == "server_error" and not _has_session_cookie(resp)
    assert calls == [] and _identities(db_session, "77") == ["kw"]
    assert db_session.get(User, "g1").deleted_at is None


# ---- 합칠 대상이 아닌 경우 ----

def test_non_guest_login_has_no_guest_merged_query(app_client, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    calls = _recording_steps(monkeypatch)
    resp = _callback(app_client, code="auth-code", state=_start_login(app_client))
    assert _guest_merged(resp) is None and _login_error(resp) is None
    assert resp.headers["location"] == LOGIN_URL
    assert calls == []


def test_login_started_by_a_kakao_user_does_not_merge(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    _seed_user(db_session, user_id="k1")
    calls = _recording_steps(monkeypatch)
    resp = _callback(app_client, code="auth-code", state=_start_login_as(app_client, "k1"))
    assert _guest_merged(resp) is None and calls == []


@pytest.mark.parametrize("target", ["already_merged", "not_a_guest", "unknown"])
def test_state_naming_a_dead_or_non_guest_account_merges_nothing(app_client, db_session, monkeypatch, kakao_configured, target):
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "gm", deleted_at=datetime.now(timezone.utc))   # 이미 합쳐진 게스트
    _seed_user(db_session, user_id="plain")
    calls = _recording_steps(monkeypatch)
    guest_id = {"already_merged": "gm", "not_a_guest": "plain", "unknown": "nobody"}[target]

    resp = _callback_with_signed_state(app_client, _signed_state(guest_id))

    assert _guest_merged(resp) is None and _login_error(resp) is None
    assert calls == []
    assert db_session.get(User, "plain").deleted_at is None
    assert _identities(db_session, "kakao_plain") == ["plain"]   # 카카오 사용자에 두 번째 수단을 붙이지 않는다
    assert len(_identities(db_session, "7")) == 1 and _identities(db_session, "7") != [guest_id]
    assert _has_session_cookie(resp)


def test_guest_cannot_be_merged_into_itself(db_session, monkeypatch):
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    assert service.merge_guest_into(db_session, guest_user_id="g1", to_user_id="g1") is None
    assert calls == [] and db_session.get(User, "g1").deleted_at is None


def test_same_guest_is_merged_only_once(db_session, monkeypatch):
    _seed_user(db_session, user_id="k1")
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    assert service.merge_guest_into(db_session, guest_user_id="g1", to_user_id="k1") is True
    assert service.merge_guest_into(db_session, guest_user_id="g1", to_user_id="k1") is None
    assert len(calls) == len(STEP_NAMES)


def test_forged_guest_id_in_state_cookie_is_invalid_state_and_merges_nothing(app_client, db_session, monkeypatch, kakao_configured):
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "victim")
    calls = _recording_steps(monkeypatch)
    _start_login(app_client)   # 게스트 아닌 시작
    state, issued_at, signature = _state_cookie_value(app_client).split(".")
    app_client.cookies.clear()   # 진짜 쿠키가 같이 실리지 않게 비운다
    app_client.cookies.set("kakao_oauth_state", f"{state}.{issued_at}.victim.{signature}", path="/")   # 서명 없이 게스트 id를 붙임

    resp = _callback(app_client, code="auth-code", state=state)

    assert _login_error(resp) == "invalid_state" and calls == []
    assert db_session.get(User, "victim").deleted_at is None
    assert _identities(db_session, "7") == []


def test_guest_merged_replaces_same_named_query_and_keeps_the_rest_of_entry_url(app_client, db_session, monkeypatch, kakao_configured):
    import dataclasses

    import auth.router as router_module

    entry = "http://localhost:5173/login?next=%2Fm%2F1&guest_merged=stale#top"
    monkeypatch.setattr(router_module, "settings", dataclasses.replace(router_module.settings, frontend_login_redirect_url=entry))
    _mock_kakao_login(monkeypatch)
    _seed_guest(db_session, "g1")
    _recording_steps(monkeypatch)

    resp = _callback(app_client, code="auth-code", state=_start_login_as(app_client, "g1"))

    location = urlparse(resp.headers["location"])
    assert parse_qs(location.query) == {"next": ["/m/1"], "guest_merged": ["true"]}
    assert location.fragment == "top"


def test_kakao_failure_for_a_guest_login_keeps_the_guest_and_adds_no_merge_query(app_client, db_session, monkeypatch, kakao_configured):
    _seed_guest(db_session, "g1")
    calls = _recording_steps(monkeypatch)
    monkeypatch.setattr(service.httpx, "post", lambda url, **kw: _FakeResponse(400, {}))

    resp = _callback(app_client, code="bad", state=_start_login_as(app_client, "g1"))

    assert _login_error(resp) == "kakao_failed" and _guest_merged(resp) is None
    assert calls == [] and db_session.get(User, "g1").deleted_at is None
    assert db_session.get(User, "g1").is_guest is True
