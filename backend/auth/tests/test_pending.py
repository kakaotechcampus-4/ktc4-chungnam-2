"""탈퇴 계정 복구 기간·선택 대기·GET/POST /auth/pending·정리(#855, #857).

실제 PostgreSQL. 같은 식별자의 동시 선택은 순차 테스트로 검증할 수 없다 — 잠금 뒤 다시 읽는 대조(`_pending_target`)가
두 번째 요청을 404로 돌려보내는 것으로 같은 결과를 본다(`test_second_choice_with_the_same_cookie_is_rejected`).
"""

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from auth import core, service
from auth.models import User, UserIdentity
from auth.testing import create_guest, create_kakao_user, session_cookie
from auth.tests.test_router import (  # noqa: F401 — kakao_configured는 픽스처
    _callback, _has_session_cookie, _mock_kakao_login, _start_login, kakao_configured,
)

SECRET = "s3cret"
NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


# ---- core: 기한과 쿠키 ----

def test_restore_deadline_is_seven_days_after_withdrawal():
    assert core.restore_deadline(NOW) == NOW + timedelta(days=7)


def test_restorable_until_exactly_seven_days_have_passed():
    assert core.is_restorable(NOW, NOW + timedelta(days=6, hours=23))
    assert not core.is_restorable(NOW, NOW + timedelta(days=7))
    assert not core.is_restorable(NOW, NOW + timedelta(days=7, hours=1))


@pytest.mark.parametrize("elapsed,left", [
    (timedelta(0), 7), (timedelta(hours=1), 7), (timedelta(days=1), 6), (timedelta(days=6, hours=23), 1), (timedelta(days=9), 0),
])
def test_days_left_rounds_up_and_floors_at_zero(elapsed, left):
    assert core.restore_days_left(NOW, NOW + elapsed) == left


def _cookie(**overrides):
    args = {"user_id": "u1", "provider": "kakao", "deleted_at": NOW, "secret": SECRET, "issued_at": 1000}
    return core.create_pending_cookie_value(**{**args, **overrides})


def test_pending_cookie_round_trips():
    claims = core.parse_pending_cookie(_cookie(), secret=SECRET, now=1100)
    assert claims == core.PendingClaims("u1", "kakao", core.deleted_at_stamp(NOW))


@pytest.mark.parametrize("mutate", [
    lambda c: c[:-1] + ("0" if c[-1] != "0" else "1"),          # 서명 변조
    lambda c: c.replace("u1.", "u2.", 1),                        # 다른 사용자
    lambda c: c.replace(".kakao.", ".qa.", 1),                   # 다른 로그인 수단
    lambda c: "x." + c,                                          # 조각 수가 다르다
    lambda c: "",                                                # 빈 값
])
def test_pending_cookie_rejects_tampering(mutate):
    assert core.parse_pending_cookie(mutate(_cookie()), secret=SECRET, now=1100) is None


def test_pending_cookie_rejects_other_secret_expiry_and_the_future():
    assert core.parse_pending_cookie(_cookie(), secret="other", now=1100) is None
    assert core.parse_pending_cookie(_cookie(), secret=SECRET, now=1000 + core.PENDING_TTL_SECONDS + 1) is None
    assert core.parse_pending_cookie(_cookie(), secret=SECRET, now=999) is None


def test_pending_cookie_is_bound_to_the_withdrawal_time():
    """같은 사용자의 다음 탈퇴 회차는 탈퇴 시각이 달라 쿠키 값이 다르다 — 서명된 시각을 바꿀 수 없다."""
    claims = core.parse_pending_cookie(_cookie(), secret=SECRET, now=1100)
    later = core.parse_pending_cookie(_cookie(deleted_at=NOW + timedelta(seconds=1)), secret=SECRET, now=1100)
    assert claims.deleted_stamp != later.deleted_stamp
    forged = _cookie().replace(str(claims.deleted_stamp), str(later.deleted_stamp))
    assert core.parse_pending_cookie(forged, secret=SECRET, now=1100) is None


def test_session_state_and_pending_cookies_do_not_stand_in_for_each_other():
    state_cookie = core.create_state_cookie_value("st", secret=SECRET, issued_at=1000)
    session_token = core.create_session_token("u1", secret=SECRET, issued_at=1000)
    assert core.parse_pending_cookie(state_cookie, secret=SECRET, now=1100) is None
    assert core.parse_pending_cookie(session_token, secret=SECRET, now=1100) is None


def test_pending_cookie_path_is_the_parent_of_the_state_cookie_path():
    assert core.pending_cookie_path("http://localhost:8000/auth/kakao/callback") == "/auth"
    assert core.pending_cookie_path("https://pingo.example/api/auth/kakao/callback") == "/api/auth"


# ---- 흐름: 탈퇴 → 로그인 → 선택 ----

def _withdrawn_account(db_session, *, user_id="old", kakao_id="77", ago=timedelta(hours=1), name="영희"):
    """탈퇴한 지 `ago` 된 카카오 사용자."""
    deleted_at = datetime.now(timezone.utc) - ago
    return create_kakao_user(
        db_session, user_id, provider_user_id=kakao_id, display_name=name,
        deleted_at=deleted_at, sessions_valid_after=deleted_at,
    )


def _login_to_pending(app_client, monkeypatch, *, kakao_id=77):
    _mock_kakao_login(monkeypatch, kakao_id=kakao_id)
    resp = _callback(app_client, code="auth-code", state=_start_login(app_client))
    assert parse_qs(urlparse(resp.headers["location"]).query).get("login_pending") == ["withdrawn_account"], resp.headers
    return resp


def _choose(client, choice, **kwargs):
    return client.post("/auth/pending", json={"choice": choice}, **kwargs)


def test_pending_cookie_has_the_agreed_attributes(app_client, db_session, monkeypatch, kakao_configured):
    _withdrawn_account(db_session)
    resp = _login_to_pending(app_client, monkeypatch)

    header = next(h for h in resp.headers.get_list("set-cookie") if h.startswith("pending_account="))
    assert "HttpOnly" in header and "Path=/auth" in header and "SameSite=lax" in header
    assert f"Max-Age={core.PENDING_TTL_SECONDS}" in header
    assert not _has_session_cookie(resp)


def test_get_pending_describes_the_withdrawn_account(app_client, db_session, monkeypatch, kakao_configured):
    old = _withdrawn_account(db_session, ago=timedelta(days=2, hours=1))
    _login_to_pending(app_client, monkeypatch)

    resp = app_client.get("/auth/pending")

    assert resp.status_code == 200
    body = resp.json()
    assert body["display_name"] == "영희" and body["days_left"] == 5
    parse = lambda value: datetime.fromisoformat(value.replace("Z", "+00:00"))   # noqa: E731 — 3.10은 Z를 못 읽는다
    assert parse(body["withdrawn_at"]) == old.deleted_at
    assert parse(body["restore_until"]) == old.deleted_at + timedelta(days=7)


def test_get_pending_without_a_cookie_is_404(app_client, kakao_configured):
    resp = app_client.get("/auth/pending")
    assert resp.status_code == 404 and resp.json()["code"] == "NO_PENDING_LOGIN"


def test_restore_gives_the_account_back_with_a_working_session(app_client, db_session, monkeypatch, kakao_configured):
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)

    resp = _choose(app_client, "restore")

    assert resp.status_code == 200
    assert resp.json() == {"id": "old", "display_name": "영희", "is_guest": False}
    assert db_session.get(User, "old").deleted_at is None
    assert app_client.get("/auth/me").json()["id"] == "old"   # 같은 초에 발급된 새 세션이 통한다
    assert any(h.startswith("pending_account=") and "Max-Age=0" in h for h in resp.headers.get_list("set-cookie"))


def test_restore_keeps_sessions_issued_before_the_withdrawal_dead(app_client, db_session, monkeypatch, kakao_configured):
    """탈퇴 전에 복사된 30일 토큰이 복구 뒤에 되살아나지 않는다(#855)."""
    old = _withdrawn_account(db_session, ago=timedelta(hours=1))
    stale = {"session": core.create_session_token(
        "old", secret=_secret(),
        issued_at=int((old.deleted_at - timedelta(minutes=5)).timestamp()),
    )}
    _login_to_pending(app_client, monkeypatch)
    _choose(app_client, "restore")

    resp = _other(app_client).get("/auth/me", cookies=stale)

    assert resp.status_code == 401


def _secret():
    from common.settings import settings

    return settings.session_secret


def _other(app_client):
    from fastapi.testclient import TestClient

    return TestClient(app_client.app)


def test_restart_makes_a_new_account_and_purges_the_old_one(app_client, db_session, monkeypatch, kakao_configured):
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)

    resp = _choose(app_client, "restart")

    assert resp.status_code == 201
    new_id = resp.json()["id"]
    assert new_id != "old" and resp.json()["is_guest"] is False
    assert app_client.get("/auth/me").json()["id"] == new_id
    identities = db_session.execute(select(UserIdentity.user_id).where(UserIdentity.provider_user_id == "77")).scalars().all()
    assert identities == [new_id]   # 같은 카카오 식별자가 새 사용자에게 붙었다
    old = db_session.get(User, "old")
    assert old.display_name == core.WITHDRAWN_DISPLAY_NAME and old.deleted_at is not None
    assert db_session.execute(select(UserIdentity).where(UserIdentity.user_id == "old")).first() is None


def test_second_choice_with_the_same_cookie_is_rejected(app_client, db_session, monkeypatch, kakao_configured):
    """같은 선택의 재전송, 그리고 동시 restore·restart에서 늦게 잠금을 잡은 쪽이 보는 상태와 같다 — 404."""
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)
    cookie = app_client.cookies.get("pending_account")
    assert _choose(app_client, "restart").status_code == 201

    for choice in ("restore", "restart"):
        resp = _other(app_client).post("/auth/pending", json={"choice": choice}, cookies={"pending_account": cookie})
        assert resp.status_code == 404 and resp.json()["code"] == "NO_PENDING_LOGIN"


def test_restore_after_restore_is_rejected(app_client, db_session, monkeypatch, kakao_configured):
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)
    cookie = app_client.cookies.get("pending_account")
    assert _choose(app_client, "restore").status_code == 200

    resp = _other(app_client).post("/auth/pending", json={"choice": "restore"}, cookies={"pending_account": cookie})

    assert resp.status_code == 404


def test_cookie_of_an_earlier_withdrawal_does_not_work_after_the_next_one(app_client, db_session, monkeypatch, kakao_configured):
    """복구한 뒤 다시 탈퇴하면 탈퇴 시각이 달라진다 — 앞 회차의 쿠키는 통하지 않는다."""
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)
    cookie = app_client.cookies.get("pending_account")
    assert _choose(app_client, "restore").status_code == 200
    service.withdraw_user(db_session, user_id="old")
    db_session.commit()   # 아래 404가 요청 트랜잭션을 되돌려도 이 탈퇴는 남는다

    other = _other(app_client)
    assert other.get("/auth/pending", cookies={"pending_account": cookie}).status_code == 404
    assert other.post("/auth/pending", json={"choice": "restore"}, cookies={"pending_account": cookie}).status_code == 404
    assert db_session.get(User, "old").deleted_at is not None


def test_tampered_cookie_is_404(app_client, db_session, monkeypatch, kakao_configured):
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)
    cookie = app_client.cookies.get("pending_account")
    forged = cookie[:-1] + ("0" if cookie[-1] != "0" else "1")

    other = _other(app_client)
    assert other.get("/auth/pending", cookies={"pending_account": forged}).status_code == 404
    assert other.post("/auth/pending", json={"choice": "restore"}, cookies={"pending_account": forged}).status_code == 404
    assert db_session.get(User, "old").deleted_at is not None


def test_cookie_for_another_identity_does_not_reach_a_different_account(app_client, db_session, monkeypatch, kakao_configured):
    """다른 사람의 쿠키 값(서명은 맞지만 그 사람의 계정)으로는 자기 계정을 건드릴 수 없다 — 쿠키는 사용자 id에 묶인다."""
    _withdrawn_account(db_session, user_id="old", kakao_id="77")
    other_user = _withdrawn_account(db_session, user_id="old2", kakao_id="78", name="민수")
    _login_to_pending(app_client, monkeypatch, kakao_id=77)

    assert app_client.get("/auth/pending").json()["display_name"] == "영희"
    assert db_session.get(User, other_user.id).deleted_at is not None


def test_choice_needs_a_json_body(app_client, db_session, monkeypatch, kakao_configured):
    """폼·text/plain·헤더 없는 교차 사이트 POST는 쿠키를 싣고 와도 아무것도 바꾸지 못한다."""
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)

    for kwargs in ({"content": '{"choice":"restore"}', "headers": {"content-type": "text/plain"}},
                   {"data": {"choice": "restore"}},
                   {"content": '{"choice":"restore"}', "headers": {"content-type": ""}}):
        resp = app_client.post("/auth/pending", **kwargs)
        assert resp.status_code == 422, kwargs
    assert db_session.get(User, "old").deleted_at is not None


def test_unknown_choice_is_422(app_client, db_session, monkeypatch, kakao_configured):
    _withdrawn_account(db_session)
    _login_to_pending(app_client, monkeypatch)
    assert _choose(app_client, "nope").status_code == 422
    assert _choose(app_client, "restore").status_code == 200   # 잘못된 요청이 쿠키를 쓰지 못하게 하지 않는다


# ---- 7일 경계: 지금 시각으로 판정 ----

def test_login_just_inside_the_restore_period_still_asks(app_client, db_session, monkeypatch, kakao_configured):
    _withdrawn_account(db_session, ago=timedelta(days=6, hours=23))
    _login_to_pending(app_client, monkeypatch)
    assert app_client.get("/auth/pending").json()["days_left"] == 1


def test_login_after_the_period_purges_on_the_spot_and_starts_a_new_account(
    app_client, db_session, monkeypatch, kakao_configured,
):
    """정리 작업이 아직 안 돌았어도 7일이 지났으면 선택 없이 새 계정이다 — 기존 계정은 그 자리에서 정리된다."""
    _withdrawn_account(db_session, ago=timedelta(days=7, hours=1))
    _mock_kakao_login(monkeypatch, kakao_id=77)

    resp = _callback(app_client, code="auth-code", state=_start_login(app_client))

    assert parse_qs(urlparse(resp.headers["location"]).query) == {}
    assert _has_session_cookie(resp)
    new_id = db_session.execute(select(UserIdentity.user_id).where(UserIdentity.provider_user_id == "77")).scalar_one()
    assert new_id != "old"
    old = db_session.get(User, "old")
    assert old.display_name == core.WITHDRAWN_DISPLAY_NAME and old.deleted_at is not None


def test_pending_choice_is_rejected_once_the_period_has_passed(db_session):
    old = _withdrawn_account(db_session, ago=timedelta(days=7, hours=1))
    claims = core.PendingClaims("old", "kakao", core.deleted_at_stamp(old.deleted_at))

    from common.errors import AppError

    for choose in (service.get_pending_account, service.restore_account, service.restart_account):
        with pytest.raises(AppError) as exc:
            choose(db_session, claims=claims)
        assert exc.value.code == "NO_PENDING_LOGIN"


def test_guest_started_login_after_the_period_attaches_to_the_guest(app_client, db_session, monkeypatch, kakao_configured):
    """기한이 지난 계정은 정리돼 그 카카오 계정은 처음 쓰는 것과 같다 — 게스트 계정에 수단이 붙는다."""
    from auth.tests.test_guest_merge import _start_login_as

    _withdrawn_account(db_session, ago=timedelta(days=8))
    create_guest(db_session, "g1")
    _mock_kakao_login(monkeypatch, kakao_id=77)

    resp = _callback(app_client, code="auth-code", state=_start_login_as(app_client, "g1"))

    assert parse_qs(urlparse(resp.headers["location"]).query) == {"guest_merged": ["true"]}
    assert db_session.execute(select(UserIdentity.user_id).where(UserIdentity.provider_user_id == "77")).scalar_one() == "g1"


# ---- 탈퇴한 계정의 기존 세션은 계속 거절 ----

def test_withdrawn_users_existing_session_is_still_rejected(app_client, db_session):
    _withdrawn_account(db_session)
    assert _other(app_client).get("/auth/me", cookies=session_cookie("old")).status_code == 401


# ---- 정리 ----

def test_purge_wipes_personal_data_and_is_idempotent(db_session):
    create_kakao_user(db_session, "u1", provider_user_id="pu1", display_name="영희", last_seen_at=NOW, deleted_at=NOW)

    service.purge_withdrawn_user(db_session, user_id="u1")
    service.purge_withdrawn_user(db_session, user_id="u1")

    row = db_session.get(User, "u1")
    assert row.display_name == core.WITHDRAWN_DISPLAY_NAME and row.last_seen_at is None and row.guest_invite_token is None
    assert db_session.execute(select(UserIdentity).where(UserIdentity.user_id == "u1")).first() is None
    assert row.deleted_at == NOW   # 행은 남는다 — 다른 모듈의 created_by가 가리킨다


def test_purge_clears_the_guest_invite_token_too(db_session):
    create_guest(db_session, "g1", guest_invite_token="tok", last_seen_at=NOW, deleted_at=NOW)

    service.purge_withdrawn_user(db_session, user_id="g1")

    row = db_session.get(User, "g1")
    assert row.guest_invite_token is None and row.last_seen_at is None


def test_purge_leaves_a_living_account_alone(db_session):
    create_kakao_user(db_session, "u1", provider_user_id="pu1", display_name="영희")

    service.purge_withdrawn_user(db_session, user_id="u1")

    assert db_session.get(User, "u1").display_name == "영희"
    assert db_session.execute(select(UserIdentity).where(UserIdentity.user_id == "u1")).first() is not None


# ---- 복구가 남기는 sessions_valid_after (같은 초 경계, 고정 시계) ----

class _FakeClock:
    """service·router·deps가 읽는 시계를 한 번에 고정한다. sleep은 시계를 그만큼 앞으로 보낸다."""

    def __init__(self, start: float):
        self.now = start
        self.mono = 0.0
        self.slept: list[float] = []
        self.wall_follows_sleep = True   # False면 벽시계가 멈춘다(역행·정지 흉내) — monotonic만 간다

    def time(self) -> float:
        return self.now

    def monotonic(self) -> float:
        return self.mono

    def sleep(self, seconds: float) -> None:
        assert seconds >= 0, "음수 sleep"
        self.slept.append(seconds)
        self.mono += seconds
        if self.wall_follows_sleep:
            self.now += seconds


@pytest.fixture()
def clock(monkeypatch):
    from types import SimpleNamespace

    from auth import deps, router

    fake = _FakeClock(1_800_000_000.4)
    namespace = SimpleNamespace(time=fake.time, sleep=fake.sleep, monotonic=fake.monotonic)
    for module in (service, router, deps):
        monkeypatch.setattr(module, "time", namespace)
    return fake


def _token(user_id, issued_at):
    return {"session": core.create_session_token(user_id, secret=_secret(), issued_at=issued_at)}


def _pending(user_id, deleted_at, clock):
    return {"pending_account": core.create_pending_cookie_value(
        user_id, "kakao", deleted_at, secret=_secret(), issued_at=int(clock.now),
    )}


def _withdraw_now(db_session, user_id, clock):
    row = service.withdraw_user(db_session, user_id=user_id)
    assert row.sessions_valid_after == row.deleted_at == datetime.fromtimestamp(clock.now, timezone.utc)
    db_session.commit()
    return row


def test_restore_in_the_same_second_waits_for_the_next_second_and_issues_no_future_token(app_client, db_session, clock):
    """탈퇴와 같은 초에 복구하면 다음 초까지 기다린 뒤 진행한다. 탈퇴 직전 그 초의 토큰은 401, 복구 뒤 새 토큰은 200,
    새 토큰의 발급 시각은 미래가 아니다(#855)."""
    create_kakao_user(db_session, "same", provider_user_id="s1", display_name="영희")
    stale = _token("same", int(clock.now))
    row = _withdraw_now(db_session, "same", clock)
    client = _other(app_client)

    resp = client.post("/auth/pending", json={"choice": "restore"}, cookies=_pending("same", row.deleted_at, clock))

    assert resp.status_code == 200
    assert len(clock.slept) == 1 and 0 < clock.slept[0] <= 1   # 최대 1초
    assert int(clock.now) == int(row.sessions_valid_after.timestamp()) + 1
    token = client.cookies.get("session")
    claims = core.parse_session_token(token, secret=_secret(), now=int(clock.now))
    assert claims is not None and claims.issued_at <= int(clock.now)   # 미래 iat가 아니다
    assert client.get("/auth/me").status_code == 200
    assert _other(app_client).get("/auth/me", cookies=stale).status_code == 401
    assert db_session.get(User, "same").sessions_valid_after == row.sessions_valid_after   # 값을 내리지 않았다


def test_restore_after_the_second_has_passed_does_not_wait(app_client, db_session, clock):
    create_kakao_user(db_session, "late", provider_user_id="l1", display_name="영희")
    row = _withdraw_now(db_session, "late", clock)
    clock.now += 5
    client = _other(app_client)

    assert client.post("/auth/pending", json={"choice": "restore"}, cookies=_pending("late", row.deleted_at, clock)).status_code == 200
    assert clock.slept == []


def test_logout_right_after_a_same_second_restore_kills_the_restored_session(app_client, db_session, clock):
    """복구 토큰이 로그아웃 뒤에도 사는 일이 없다 — 로그아웃은 평소처럼 동작한다."""
    create_kakao_user(db_session, "out", provider_user_id="o1", display_name="영희")
    row = _withdraw_now(db_session, "out", clock)
    client = _other(app_client)
    assert client.post("/auth/pending", json={"choice": "restore"}, cookies=_pending("out", row.deleted_at, clock)).status_code == 200
    restored = {"session": client.cookies.get("session")}

    assert client.post("/auth/logout").status_code == 204

    assert _other(app_client).get("/auth/me", cookies=restored).status_code == 401


def test_withdraw_and_restore_repeated_in_the_same_second_never_revives_an_earlier_token(app_client, db_session, clock):
    """탈퇴·복구를 반복해도 직전 회차의 토큰은 되살아나지 않는다."""
    create_kakao_user(db_session, "loop", provider_user_id="p1", display_name="영희")
    seen: list[dict] = []
    for _ in range(3):
        row = _withdraw_now(db_session, "loop", clock)
        client = _other(app_client)
        assert client.post("/auth/pending", json={"choice": "restore"}, cookies=_pending("loop", row.deleted_at, clock)).status_code == 200
        current = {"session": client.cookies.get("session")}
        assert _other(app_client).get("/auth/me", cookies=current).status_code == 200
        for earlier in seen:
            assert _other(app_client).get("/auth/me", cookies=earlier).status_code == 401
        seen.append(current)
        # 복구 직후 같은 초 안에 다시 탈퇴한다 — 시계는 앞으로만 간다


def test_restore_waiting_for_the_next_second_is_rejected_if_the_period_ended_meanwhile(db_session, clock):
    """기한 1초 직전의 복구가 다음 초를 기다리는 사이 기한이 지나면 거절한다."""
    from common.errors import AppError

    deleted_at = datetime.fromtimestamp(clock.now, timezone.utc) - timedelta(days=core.ACCOUNT_RESTORE_DAYS) + timedelta(seconds=0.3)
    create_kakao_user(db_session, "edge", provider_user_id="e1", deleted_at=deleted_at, sessions_valid_after=datetime.fromtimestamp(clock.now, timezone.utc))
    claims = core.PendingClaims("edge", "kakao", core.deleted_at_stamp(deleted_at))

    with pytest.raises(AppError) as exc:
        service.restore_account(db_session, claims=claims)

    assert exc.value.code == "NO_PENDING_LOGIN" and db_session.get(User, "edge").deleted_at is not None


def test_restore_of_a_row_without_sessions_valid_after_uses_the_withdrawal_time(db_session):
    """이 기능 전에 탈퇴한 행은 sessions_valid_after가 없다 — 복구가 탈퇴 시각을 넣어 그 이전 토큰을 죽인다."""
    old = _withdrawn_account(db_session)
    old.sessions_valid_after = None
    db_session.flush()
    deleted_at = old.deleted_at

    service.restore_account(db_session, claims=core.PendingClaims("old", "kakao", core.deleted_at_stamp(deleted_at)))

    assert db_session.get(User, "old").sessions_valid_after == deleted_at


# ---- 선택 대기 쿠키의 형식 오류는 모두 None ----

@pytest.mark.parametrize("mutate", [
    lambda c: c.replace(c.split(".")[2], "²"),                      # isdigit()은 참, int()는 실패
    lambda c: c.replace(c.split(".")[3], "١٢٣"),                    # 아랍-인도 숫자
    lambda c: c[: c.rindex(".") + 1] + "서명",                       # 비ASCII 서명
    lambda c: c[: c.rindex(".") + 1],                                # 빈 서명
    lambda c: c + "\x00",
])
def test_pending_cookie_with_malformed_fields_is_none_not_an_exception(mutate):
    assert core.parse_pending_cookie(mutate(_cookie()), secret=SECRET, now=1100) is None


def test_pending_endpoint_with_a_malformed_cookie_is_404_not_500(app_client):
    """브라우저가 latin-1 바이트를 그대로 보내는 경우 — 서버는 그 값을 '²' 같은 문자로 읽는다."""
    client = _other(app_client)
    for value in ("u.kakao.²." + "1" * 10 + ".sig", "u.kakao.1.1.sigé"):
        resp = client.get("/auth/pending", headers={"cookie": ("pending_account=" + value).encode("latin-1")})
        assert resp.status_code == 404 and resp.json()["code"] == "NO_PENDING_LOGIN"


# ---- 잠금을 기다리는 사이 기한이 지나는 경우(실제 두 DB 연결) ----

def test_choice_waiting_on_the_lock_is_rejected_if_the_period_ends_meanwhile(test_engine):
    """기한 2.5초 전에 도착한 선택이 식별자 잠금에서 기다리다 기한이 지난 뒤 잠금을 얻으면 거절된다(404). 기한은 잠금을 얻은 뒤
    지금 시각으로 판정한다."""
    import threading
    import time

    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from common.errors import AppError

    factory = sessionmaker(bind=test_engine)
    deleted_at = datetime.now(timezone.utc) - timedelta(days=core.ACCOUNT_RESTORE_DAYS) + timedelta(seconds=2.5)
    with factory() as setup:
        create_kakao_user(setup, "lockwait", provider_user_id="lw1", display_name="영희", deleted_at=deleted_at)
        setup.commit()
    claims = core.PendingClaims("lockwait", "kakao", core.deleted_at_stamp(deleted_at))
    outcome: dict = {}

    def choose():
        with factory() as db:
            try:
                service.restore_account(db, claims=claims)
                db.commit()
                outcome["result"] = "restored"
            except AppError as exc:
                db.rollback()
                outcome["result"] = exc.code

    holder = test_engine.connect()
    try:
        tx = holder.begin()
        holder.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": "login_identity:kakao:lw1"})
        worker = threading.Thread(target=choose)
        worker.start()
        for _ in range(100):   # 선택이 정말 잠금에서 기다릴 때까지
            waiting = holder.execute(text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND NOT granted")).scalar()
            if waiting:
                break
            time.sleep(0.05)
        assert waiting, "선택이 잠금을 기다리지 않았다"
        assert core.is_restorable(deleted_at, datetime.now(timezone.utc))   # 기다리기 시작할 때는 기한 안이었다
        time.sleep(3)                                                        # 기다리는 사이 기한이 지난다
        tx.rollback()
        worker.join(timeout=10)
    finally:
        holder.close()
        with factory() as cleanup:
            cleanup.execute(text("DELETE FROM user_identities WHERE user_id = 'lockwait'"))
            row_deleted_at = cleanup.get(User, "lockwait").deleted_at
            cleanup.execute(text("DELETE FROM users WHERE id = 'lockwait'"))
            cleanup.commit()

    assert outcome == {"result": "NO_PENDING_LOGIN"}
    assert row_deleted_at is not None   # 되살려지지 않았다


# ---- 정기 정리(purge_withdrawn_accounts) ----

def _identity_count(db_session, user_id):
    return db_session.query(UserIdentity).filter_by(user_id=user_id).count()


def test_purge_withdrawn_accounts_wipes_only_accounts_past_the_period(db_session):
    now = datetime.now(timezone.utc)
    create_kakao_user(db_session, "past", provider_user_id="a", display_name="영희", last_seen_at=now, deleted_at=now - timedelta(days=7, hours=1))
    create_kakao_user(db_session, "inside", provider_user_id="b", display_name="민수", deleted_at=now - timedelta(days=6, hours=23))
    create_kakao_user(db_session, "alive", provider_user_id="c", display_name="철수")

    assert service.purge_withdrawn_accounts(db_session, now=now) == 1

    assert db_session.get(User, "past").display_name == core.WITHDRAWN_DISPLAY_NAME and _identity_count(db_session, "past") == 0
    assert db_session.get(User, "inside").display_name == "민수" and _identity_count(db_session, "inside") == 1
    assert db_session.get(User, "alive").display_name == "철수" and _identity_count(db_session, "alive") == 1


def test_purge_withdrawn_accounts_is_idempotent_and_skips_already_purged(db_session):
    now = datetime.now(timezone.utc)
    create_kakao_user(db_session, "past", provider_user_id="a", deleted_at=now - timedelta(days=8))
    create_kakao_user(db_session, "done", provider_user_id="d", deleted_at=now - timedelta(days=9))
    service.purge_withdrawn_user(db_session, user_id="done")

    assert service.purge_withdrawn_accounts(db_session, now=now) == 1
    assert service.purge_withdrawn_accounts(db_session, now=now) == 0


def test_purge_withdrawn_accounts_covers_withdrawn_guests(db_session):
    now = datetime.now(timezone.utc)
    create_guest(db_session, "g1", guest_invite_token="tok", last_seen_at=now, deleted_at=now - timedelta(days=8))

    assert service.purge_withdrawn_accounts(db_session, now=now) == 1

    row = db_session.get(User, "g1")
    assert row.display_name == core.WITHDRAWN_DISPLAY_NAME and row.guest_invite_token is None and row.last_seen_at is None


def test_purge_withdrawn_accounts_leaves_no_personal_data_in_users_or_identities(db_session):
    now = datetime.now(timezone.utc)
    create_kakao_user(db_session, "past", provider_user_id="kakao-secret-id", display_name="개인이름", deleted_at=now - timedelta(days=8))

    service.purge_withdrawn_accounts(db_session, now=now)

    rows = db_session.execute(select(User.display_name)).scalars().all()
    assert "개인이름" not in rows
    assert db_session.execute(select(UserIdentity).where(UserIdentity.provider_user_id == "kakao-secret-id")).first() is None


def test_purged_account_can_not_be_chosen_any_more(db_session):
    from common.errors import AppError

    now = datetime.now(timezone.utc)
    row = create_kakao_user(db_session, "past", provider_user_id="a", deleted_at=now - timedelta(days=8))
    claims = core.PendingClaims("past", "kakao", core.deleted_at_stamp(row.deleted_at))
    service.purge_withdrawn_accounts(db_session, now=now)

    with pytest.raises(AppError) as exc:
        service.restore_account(db_session, claims=claims)
    assert exc.value.code == "NO_PENDING_LOGIN"


def test_api_purge_withdrawn_accounts_delegates_to_the_service(db_session):
    from auth import api as auth_api

    now = datetime.now(timezone.utc)
    create_kakao_user(db_session, "past", provider_user_id="a", deleted_at=now - timedelta(days=8))
    assert auth_api.purge_withdrawn_accounts(db_session, now) == 1


# ---- 아주 긴 숫자열·비ASCII 숫자는 어느 토큰에서도 예외가 아니라 None ----

@pytest.mark.parametrize("digits", ["1" * 4301, "1" * 13, "²", "١٢٣"])
def test_long_or_non_ascii_digit_fields_are_rejected_without_an_exception(digits):
    pending = f"u1.kakao.{digits}.1000.sig"
    assert core.parse_pending_cookie(pending, secret=SECRET, now=1100) is None
    assert core.parse_pending_cookie(f"u1.kakao.1.{digits}.sig", secret=SECRET, now=1100) is None
    assert core.parse_session_token(f"u1.{digits}.sig", secret=SECRET, now=1100) is None
    assert core.parse_state(f"st.{digits}.sig", "st", secret=SECRET, now=1100) is None


def test_pending_endpoint_with_a_very_long_number_cookie_is_404(app_client):
    client = _other(app_client)
    value = "u.kakao." + "1" * 4301 + ".1000.sig"
    assert client.get("/auth/pending", cookies={"pending_account": value}).status_code == 404
    resp = client.post("/auth/pending", json={"choice": "restore"}, cookies={"pending_account": value})
    assert resp.status_code == 404 and resp.json()["code"] == "NO_PENDING_LOGIN"


# ---- 기다림의 경계: 시계 역행·정지, 초 경계 넘김 ----

def _withdrawn_at(db_session, user_id, clock, *, valid_after_offset=0.0):
    deleted_at = datetime.fromtimestamp(clock.now, timezone.utc)
    create_kakao_user(
        db_session, user_id, provider_user_id=f"w_{user_id}", display_name="영희",
        deleted_at=deleted_at, sessions_valid_after=datetime.fromtimestamp(clock.now + valid_after_offset, timezone.utc),
    )
    return deleted_at, core.PendingClaims(user_id, "kakao", core.deleted_at_stamp(deleted_at))


def test_wait_never_sleeps_a_negative_time_when_the_second_rolls_over_between_reads(db_session, clock):
    """초 경계 직전(.999)에 읽어도 sleep 인자는 음수가 아니다 — 시계를 한 번만 읽어 남은 시간을 구한다."""
    clock.now = 1_800_000_000.999
    _, claims = _withdrawn_at(db_session, "edge1", clock)
    reads = iter([clock.now, clock.now + 0.002])   # 두 번 읽으면 두 번째는 다음 초

    def flipping_time():
        return next(reads, clock.now)

    from types import SimpleNamespace

    from auth import service as svc

    svc.time = SimpleNamespace(time=flipping_time, sleep=clock.sleep, monotonic=clock.monotonic)   # clock 픽스처가 되돌린다
    user = service.restore_account(db_session, claims=claims)

    assert user.deleted_at is None and all(s >= 0 for s in clock.slept)


def test_clock_going_backwards_gives_up_with_a_retryable_error_and_leaves_the_account_alone(db_session, clock):
    """valid_after가 지금보다 2초 넘게 앞선 경우(시계 역행)엔 총 2초(monotonic)까지만 기다리고, 복구하지 않고 재시도 가능한 오류."""
    from common.errors import AppError

    deleted_at, claims = _withdrawn_at(db_session, "back", clock, valid_after_offset=5.0)
    clock.wall_follows_sleep = False

    with pytest.raises(AppError) as exc:
        service.restore_account(db_session, claims=claims)

    assert exc.value.code == "INTERNAL_ERROR" and exc.value.code != "NO_PENDING_LOGIN"
    assert sum(clock.slept) <= 2.0 + 1e-9
    row = db_session.get(User, "back")
    assert row.deleted_at == deleted_at   # 계정 상태 그대로
    assert row.sessions_valid_after == datetime.fromtimestamp(clock.now + 5.0, timezone.utc)


def test_far_ahead_valid_after_is_waited_out_when_the_clock_catches_up_in_time(db_session, clock):
    """valid_after가 1.5초 앞이어도 벽시계가 따라가면(상한 2초 안) 기다린 뒤 복구한다."""
    _, claims = _withdrawn_at(db_session, "ahead", clock, valid_after_offset=1.5)

    user = service.restore_account(db_session, claims=claims)

    assert user.deleted_at is None and int(clock.now) > int(user.sessions_valid_after.timestamp())


def test_period_ending_during_a_slow_wait_is_rechecked_each_round(db_session, clock):
    """기다리는 도중 기한이 지나면(여러 번 돌 때마다 다시 확인) NO_PENDING_LOGIN이다."""
    from common.errors import AppError

    now = datetime.fromtimestamp(clock.now, timezone.utc)
    deleted_at = now - timedelta(days=core.ACCOUNT_RESTORE_DAYS) + timedelta(seconds=0.5)
    create_kakao_user(db_session, "slow", provider_user_id="w_slow", deleted_at=deleted_at,
                      sessions_valid_after=datetime.fromtimestamp(clock.now + 1.2, timezone.utc))
    claims = core.PendingClaims("slow", "kakao", core.deleted_at_stamp(deleted_at))

    with pytest.raises(AppError) as exc:
        service.restore_account(db_session, claims=claims)

    assert exc.value.code == "NO_PENDING_LOGIN" and db_session.get(User, "slow").deleted_at is not None
