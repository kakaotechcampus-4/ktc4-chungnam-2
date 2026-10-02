"""다른 모듈 테스트가 "로그인한 사용자"를 만드는 방법을 한 곳에 둔다(authz/testing.py와 같은 원칙).

실제 인증(auth.deps.get_current_user)은 서명된 세션 토큰과 users 행을 둘 다 요구하므로,
테스트도 같은 것을 만든다 — 쿠키 문자열을 그대로 user_id로 믿는 경로는 없다(#126).
"""

import time

from sqlalchemy.orm import Session

from auth import core
from auth.models import User
from common.settings import settings


def session_cookie(user_id: str) -> dict[str, str]:
    """`cookies=`에 그대로 넘길 수 있는 서명된 세션 쿠키."""
    token = core.create_session_token(user_id, secret=settings.session_secret, issued_at=int(time.time()))
    return {"session": token}


def ensure_users(db: Session, *user_ids: str, display_names: dict[str, str] | None = None) -> None:
    """users 행이 없으면 만든다. 있으면 그대로 두되, display_names로 이름을 명시한 사용자만 이름을 바꾼다.
    인증이 요청마다 이 행으로 탈퇴 여부를 확인한다."""
    names = display_names or {}
    for user_id in user_ids:
        row = db.get(User, user_id)
        if row is None:
            db.add(User(id=user_id, provider="kakao", provider_user_id=f"test_{user_id}",
                        display_name=names.get(user_id, user_id)))
        elif user_id in names:
            row.display_name = names[user_id]
    db.flush()
