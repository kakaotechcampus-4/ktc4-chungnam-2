"""
스테이징 전용 QA 로그인 `POST /auth/qa-login`(#788, #789). FE는 쓰지 않는다 — QA 하네스가 카카오 없이 사용자를 만든다.

main.py가 `settings.qa_login_enabled`(staging + QA_LOGIN_SECRET)일 때만 이 라우터를 붙인다. 그 밖의 환경에는 경로가 없다.
비밀값 확인은 라우터 의존성이라 본문 검증보다 먼저 돈다 — 비밀값이 틀린 요청은 본문이 어떻든 403이다.
비밀값·헤더·이름은 로그에 남기지 않는다.
"""

import hmac

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.orm import Session

from auth import service
from auth.deps import DbSession
from auth.router import _set_session_cookie, _user_response
from auth.schemas import QaLoginRequest, UserResponse
from common.errors import AppError
from common.settings import settings


def _require_qa_secret(x_qa_login_secret: str | None = Header(default=None)) -> None:
    expected = settings.qa_login_secret
    # bytes로 비교한다 — str끼리면 ASCII 밖의 글자가 든 헤더에서 compare_digest가 TypeError를 낸다
    if not expected or not x_qa_login_secret or not hmac.compare_digest(
        x_qa_login_secret.encode(), expected.encode(),
    ):
        raise AppError("FORBIDDEN")


router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(_require_qa_secret)])


@router.post("/qa-login", response_model=UserResponse, status_code=201)
def post_qa_login(body: QaLoginRequest, response: Response, db: Session = DbSession):
    row = service.create_qa_user(db, display_name=body.display_name)
    _set_session_cookie(response, row.id)
    return _user_response(row)
