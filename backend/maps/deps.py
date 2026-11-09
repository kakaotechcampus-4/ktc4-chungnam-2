"""
FastAPI 의존성 배선 — DB 세션만(backend/pins/deps.py·backend/shortlist/deps.py와 같은 패턴).
멤버십 게이트웨이는 여기 두지 않는다 — authz.deps.get_membership_gateway를 다른 모듈이
바꿔 끼우는 건 이 파일이 아니라 maps/api.py::DbMembershipGateway를 통해서다(authz/deps.py,
#89). 이 파일에 `get_membership_gateway`라는 이름을 두면
common/tests/test_adapter_assembly.py::test_adapter_factories_go_through_select가 select()
우회로 잡는다 — 애초에 두지 않는다.
"""

from fastapi import Cookie, Depends
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from common.database import get_db_session
from common.errors import AppError

DbSession = Depends(get_db_session)


def get_optional_user(
    session: str | None = Cookie(default=None), db: Session = Depends(get_db_session)
) -> CurrentUser | None:
    """로그인 없이도 열리는 경로(GET /invites/{token})용 선택적 인증(#1563). 세션이 없거나 유효하지 않으면
    401 대신 None이다 — 판정은 get_current_user 한 곳이 하고, 여기서는 그 UNAUTHORIZED만 None으로 바꾼다."""
    try:
        return get_current_user(session, db)
    except AppError as exc:
        if exc.code == "UNAUTHORIZED":
            return None
        raise
