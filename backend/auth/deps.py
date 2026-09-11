"""
인증 의존성 — 인증이 필요한 모든 모듈이 라우터 선언에서 가져다 쓰는 단일 진입점
(mentor-review-plan.md 결정: ASGI 미들웨어가 아니라 FastAPI 라우터 의존성).

    from auth.deps import get_current_user
    router = APIRouter(tags=["pins"], dependencies=[Depends(get_current_user)])

이렇게 라우터 선언에 박아두면 개별 엔드포인트 함수가 인증을 따로 기억할 필요가 없다 —
멘토 코멘트 4가 지적한 "라우터마다 세션 해석을 반복" 문제가 여기서 사라진다.

get_current_user는 common.adapters.select()를 거친다 — settings.auth_mode가 "real"인데
실구현(#4)이 없으면 여기서 ConfigError로 서버가 뜨기 전에 죽는다. prod에서 이 개발용 스텁이
선택되는 것도 select()가 막는다(Settings.__post_init__과 select() 양쪽에서 이중으로 걸린다 —
common/adapters.py 참고). 이걸 하기 전에는 검증 없는 쿠키 스텁이 이론상 PINGO_ENV=prod에서도
그대로 돌아갈 수 있었다 — 멘토 코멘트 6이 우려한 상황이다(auth/for_Root.md에 근거 정리).
"""

from typing import Annotated

from fastapi import Cookie, Depends

from auth.schemas import CurrentUser
from common.adapters import select
from common.errors import AppError
from common.settings import settings

# AppError의 실제 시그니처(backend/common/errors.py, 직접 확인 완료):
#   AppError(code: str, message: str | None = None, detail: dict | None = None)
# 상태 코드는 여기서 넘기지 않는다 — CATALOG[code]에서 조회한다(status < 400이면 ValueError로
# 생성 자체가 막힘).


def _dev_get_current_user(session: str | None = Cookie(default=None)) -> CurrentUser:
    """auth(#4) 도착 시 이 함수를 실구현으로 바꿔 아래 select()의 "real" 자리에 넣는다.
    401을 여기서 던져도 된다 — common/errors.py의 앱 레벨 AppError 핸들러가
    {code, message, detail?} 봉투로 변환한다(main.py가 register_error_handlers(app)을 호출)."""
    if not session:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    return CurrentUser(user_id=session)  # #4 전까지: 쿠키 문자열 = user_id


get_current_user = select(
    "auth.SessionResolver", settings.auth_mode,
    {"dev": _dev_get_current_user, "real": None}, "#4",
)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
