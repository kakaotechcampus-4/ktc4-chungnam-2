"""
인증 의존성 — 인증이 필요한 모든 모듈이 라우터 선언에서 가져다 쓰는 단일 진입점
(mentor-review-plan.md 결정: ASGI 미들웨어가 아니라 FastAPI 라우터 의존성).

    from auth.deps import get_current_user
    router = APIRouter(tags=["pins"], dependencies=[Depends(get_current_user)])

이렇게 라우터 선언에 박아두면 개별 엔드포인트 함수가 인증을 따로 기억할 필요가 없다 —
멘토 코멘트 4가 지적한 "라우터마다 세션 해석을 반복" 문제가 여기서 사라진다.

인증 구현은 하나다(#126) — 쿠키 문자열을 검증 없이 user_id로 받던 개발용 스텁과 AUTH_MODE는
없앴다. PINGO_ENV를 빠뜨려도 그 스텁이 올라갈 길이 없게 하려는 것이다. 다른 모듈 테스트는
`auth.testing`으로 서명된 세션 토큰과 users 행을 만들어 쓴다.
"""

import time
from typing import Annotated

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from auth import core, service
from auth.schemas import CurrentUser
from common.database import get_db_session
from common.errors import AppError
from common.settings import settings

# AppError의 실제 시그니처(backend/common/errors.py, 직접 확인 완료):
#   AppError(code: str, message: str | None = None, detail: dict | None = None)
# 상태 코드는 여기서 넘기지 않는다 — CATALOG[code]에서 조회한다(status < 400이면 ValueError로
# 생성 자체가 막힘).


def get_current_user(
    session: str | None = Cookie(default=None),
    db: Session = Depends(get_db_session),
) -> CurrentUser:
    """실구현 — 서명된 세션 쿠키를 검증하고, 가리키는 사용자가 실제로 존재하며 탈퇴하지
    않았는지 DB에서 재확인한다(쿠키 자체는 유효 기간 안이어도 그 사이 탈퇴했을 수 있다).
    로그아웃 이전에 발급된 토큰(이미 복사된 것 포함)은 users.sessions_valid_after로 거절한다 —
    같은 users 행 조회 한 번으로 함께 판정해 쿼리는 늘지 않는다."""
    if not session:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    claims = core.parse_session_token(session, secret=settings.session_secret, now=int(time.time()))
    if claims is None:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    row = service.get_active_user_or_401(db, user_id=claims.user_id)
    if core.is_revoked(claims.issued_at, row.sessions_valid_after):
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    return CurrentUser(user_id=claims.user_id)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
DbSession = Depends(get_db_session)
