"""
인증 의존성 — 인증이 필요한 모든 모듈이 라우터 선언에서 가져다 쓰는 단일 진입점
(mentor-review-plan.md 결정: ASGI 미들웨어가 아니라 FastAPI 라우터 의존성).

    from auth.deps import get_current_user
    router = APIRouter(tags=["pins"], dependencies=[Depends(get_current_user)])

이렇게 라우터 선언에 박아두면 개별 엔드포인트 함수가 인증을 따로 기억할 필요가 없다 —
멘토 코멘트 4가 지적한 "라우터마다 세션 해석을 반복" 문제가 여기서 사라진다.
"""

from typing import Annotated

from fastapi import Cookie, Depends

from auth.schemas import CurrentUser
from common.errors import AppError

# AppError의 실제 시그니처(backend/common/errors.py, 직접 확인 완료):
#   AppError(code: str, message: str | None = None, detail: dict | None = None)
# 상태 코드는 여기서 넘기지 않는다 — CATALOG[code]에서 조회한다(status < 400이면 ValueError로
# 생성 자체가 막힘).


def get_current_user(session: str | None = Cookie(default=None)) -> CurrentUser:
    """auth(#4) 도착 시 이 함수 본문만 실제 세션 검증으로 교체한다.
    401을 여기서 던져도 된다 — common/errors.py의 앱 레벨 AppError 핸들러가
    {code, message, detail?} 봉투로 변환한다(main.py가 register_error_handlers(app)을 호출)."""
    if not session:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    return CurrentUser(user_id=session)  # #4 전까지: 쿠키 문자열 = user_id


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
