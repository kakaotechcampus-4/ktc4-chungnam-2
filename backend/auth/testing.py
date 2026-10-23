"""다른 모듈 테스트가 "로그인한 사용자"를 만드는 방법을 한 곳에 둔다(authz/testing.py와 같은 원칙).

실제 인증(auth.deps.get_current_user)은 서명된 세션 토큰과 users 행을 둘 다 요구하므로,
테스트도 같은 것을 만든다 — 쿠키 문자열을 그대로 user_id로 믿는 경로는 없다(#126).
"""

import time

from sqlalchemy import delete
from sqlalchemy.orm import Session

from auth import core
from auth.models import User, UserIdentity
from common.settings import settings


def session_cookie(user_id: str) -> dict[str, str]:
    """`cookies=`에 그대로 넘길 수 있는 서명된 세션 쿠키."""
    token = core.create_session_token(user_id, secret=settings.session_secret, issued_at=int(time.time()))
    return {"session": token}


def create_kakao_user(
    db: Session, user_id: str | None = None, *, provider_user_id: str | None = None, display_name: str = "철수", **columns,
) -> User:
    """카카오 로그인 수단까지 가진 사용자(#694). provider_user_id를 안 주면 user_id로 만든다. columns는 users 칸
    (deleted_at, sessions_valid_after 등)."""
    row = User(display_name=display_name, **({"id": user_id} if user_id else {}), **columns)
    db.add(row)
    db.flush()
    db.add(UserIdentity(user_id=row.id, provider="kakao", provider_user_id=provider_user_id or f"test_{row.id}"))
    db.flush()
    return row


def create_guest(db: Session, user_id: str | None = None, *, display_name: str = "손님", **columns) -> User:
    """게스트 — 로그인 수단이 없는 사용자(#694). columns는 users 칸(guest_invite_token, deleted_at 등)."""
    row = User(display_name=display_name, **({"id": user_id} if user_id else {}), **columns)
    db.add(row)
    db.flush()
    return row


def make_guest(db: Session, user_id: str) -> None:
    """있는 사용자를 게스트로 바꾼다 — 로그인 수단을 지운다."""
    db.execute(delete(UserIdentity).where(UserIdentity.user_id == user_id))
    db.expire_all()


def ensure_users(db: Session, *user_ids: str, display_names: dict[str, str] | None = None) -> None:
    """users 행이 없으면 카카오 수단과 함께 만든다. 있으면 그대로 두되, display_names로 이름을 명시한 사용자만 이름을 바꾼다.
    인증이 요청마다 이 행으로 탈퇴 여부를 확인한다."""
    names = display_names or {}
    for user_id in user_ids:
        row = db.get(User, user_id)
        if row is None:
            create_kakao_user(db, user_id, display_name=names.get(user_id, user_id))
        elif user_id in names:
            row.display_name = names[user_id]
    db.flush()
