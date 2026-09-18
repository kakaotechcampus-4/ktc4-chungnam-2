"""
인증 의존성 — 인증이 필요한 모든 모듈이 라우터 선언에서 가져다 쓰는 단일 진입점
(mentor-review-plan.md 결정: ASGI 미들웨어가 아니라 FastAPI 라우터 의존성).

    from auth.deps import get_current_user
    router = APIRouter(tags=["pins"], dependencies=[Depends(get_current_user)])

이렇게 라우터 선언에 박아두면 개별 엔드포인트 함수가 인증을 따로 기억할 필요가 없다 —
멘토 코멘트 4가 지적한 "라우터마다 세션 해석을 반복" 문제가 여기서 사라진다.

get_current_user는 common.adapters.select()를 거친다 — settings.auth_mode가 "real"인데
실구현이 없으면 여기서 ConfigError로 서버가 뜨기 전에 죽는다. prod에서 dev 스텁이 선택되는
것도 select()가 막는다(Settings.__post_init__과 select() 양쪽에서 이중으로 걸린다 —
common/adapters.py 참고).

**dev/real 두 구현이 계속 공존하는 이유**: dev 스텁(`_dev_get_current_user`, 쿠키 문자열을
검증 없이 그대로 user_id로 받는다)은 auth 자신의 실구현이 생긴 뒤에도 없애지 않는다 —
pins·maps·shortlist 등 다른 모든 모듈의 통합 테스트가 이미 `cookies={"session": "user_1"}`
형태로 이 동작에 의존하고 있다(예: maps/tests/test_invites_api.py). 실서비스(prod)에서는
Settings.__post_init__이 AUTH_MODE=dev를 막으므로 이 스텁이 실제로 쓰일 일은 없다.
"""

import time
from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from auth import core, service
from auth.schemas import CurrentUser
from common.adapters import select
from common.database import get_db
from common.errors import AppError
from common.settings import settings

# AppError의 실제 시그니처(backend/common/errors.py, 직접 확인 완료):
#   AppError(code: str, message: str | None = None, detail: dict | None = None)
# 상태 코드는 여기서 넘기지 않는다 — CATALOG[code]에서 조회한다(status < 400이면 ValueError로
# 생성 자체가 막힘).


def _dev_get_current_user(session: str | None = Cookie(default=None)) -> CurrentUser:
    """검증 없는 개발용 스텁 — 쿠키 문자열을 그대로 user_id로 받는다. DB를 보지 않으므로
    users 테이블에 그 행이 실제로 있는지도 확인하지 않는다(다른 모듈 테스트가 임의의
    "user_1" 문자열을 그대로 쓸 수 있어야 하기 때문 — 위 모듈 docstring 참고)."""
    if not session:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    return CurrentUser(user_id=session)


def get_db_session():
    yield from get_db()


def _real_get_current_user(
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db_session),
) -> CurrentUser:
    """실구현 — 서명된 세션 쿠키를 검증하고, 가리키는 사용자가 실제로 존재하며 탈퇴하지
    않았는지 DB에서 재확인한다(쿠키 자체는 유효 기간 안이어도 그 사이 탈퇴했을 수 있다)."""
    if not session:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    user_id = core.parse_session_token(session, secret=settings.session_secret, now=int(time.time()))
    if user_id is None:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    service.get_active_user_or_401(db, user_id=user_id)
    return CurrentUser(user_id=user_id)


get_current_user = select(
    "auth.SessionResolver", settings.auth_mode,
    {"dev": _dev_get_current_user, "real": _real_get_current_user}, "#4",
)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DbSession = Depends(get_db_session)
