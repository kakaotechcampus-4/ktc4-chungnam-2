"""
셸 — DB·카카오 HTTP 호출만 여기 둔다. 판정 로직(토큰 서명/검증, 표시 이름 추출)은
auth/core.py(순수 함수)에 있다(docs/code-quality.md 기능형 코어/명령형 셸 분리).

각 함수는 커밋하지 않는다 — common.database.get_db(session_scope)가 요청당 한 번 커밋한다
(pins/api.py와 같은 규약).
"""

from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from auth import core
from auth.models import User
from common.errors import AppError
from common.settings import settings

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USERINFO_URL = "https://kapi.kakao.com/v2/user/me"
_HTTP_TIMEOUT_SECONDS = 5.0


def _exchange_kakao_code(code: str) -> str:
    """인가 코드 → 액세스 토큰. 실패를 조용히 삼키지 않는다 — OAuth 콜백 실패가 로그인
    성공처럼 처리되면 안 된다(auth/CLAUDE.md "코드 품질" 절)."""
    resp = httpx.post(
        KAKAO_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": settings.kakao_client_id,
            "client_secret": settings.kakao_client_secret,
            "redirect_uri": settings.kakao_redirect_uri,
            "code": code,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise AppError(
            "UNAUTHORIZED", "카카오 인증에 실패했습니다",
            detail={"kakao_status": resp.status_code},
        )
    return resp.json()["access_token"]


def _fetch_kakao_profile(access_token: str) -> dict:
    resp = httpx.get(
        KAKAO_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=_HTTP_TIMEOUT_SECONDS,
    )
    if resp.status_code != 200:
        raise AppError(
            "UNAUTHORIZED", "카카오 사용자 정보를 가져오지 못했습니다",
            detail={"kakao_status": resp.status_code},
        )
    return resp.json()


def find_or_create_user(db: Session, *, provider: str, provider_user_id: str, display_name: str) -> User:
    row = db.execute(
        select(User).where(User.provider == provider, User.provider_user_id == provider_user_id)
    ).scalar_one_or_none()
    if row is not None:
        if row.deleted_at is not None:
            # 탈퇴한 계정으로 재로그인 — 조용히 되살리지 않는다. 재활성화를 허용할지는
            # 12절 범위 밖의 별도 결정이라 지금은 막고 루트에 보고한다(auth/for_Root.md).
            raise AppError("UNAUTHORIZED", "탈퇴한 계정입니다")
        return row
    row = User(provider=provider, provider_user_id=provider_user_id, display_name=display_name)
    db.add(row)
    db.flush()
    return row


def login_with_kakao_code(db: Session, *, code: str) -> User:
    access_token = _exchange_kakao_code(code)
    profile = _fetch_kakao_profile(access_token)
    provider_user_id = str(profile["id"])
    display_name = core.display_name_from_kakao_profile(profile)
    return find_or_create_user(db, provider="kakao", provider_user_id=provider_user_id, display_name=display_name)


def get_active_user_or_401(db: Session, *, user_id: str) -> User:
    """세션이 가리키는 user_id가 실제로 존재하고 탈퇴하지 않았는지 확인한다. 탈퇴한 계정의
    세션 쿠키가 아직 브라우저에 남아있어도 여기서 즉시 막힌다."""
    row = db.get(User, user_id)
    if row is None or row.deleted_at is not None:
        raise AppError("UNAUTHORIZED", "로그인이 필요합니다")
    return row


def withdraw_user(db: Session, *, user_id: str) -> User:
    """탈퇴 처리(12절) — soft delete.

    **완료하지 못한 범위(auth/for_Root.md에 동일 내용 보고)**: 연결된 `pins.reactions`·
    `recommend.evidence_lines` 삭제는 이 함수가 하지 않는다. 다른 모듈 테이블에 직접
    쓰지 않는다는 원칙(backend/CLAUDE.md "모듈 간 접근", auth/CLAUDE.md) 때문에 여기서
    ORM으로 지울 수 없고, 대신 그 모듈이 공개한 함수를 불러야 하는데 — 확인해보니
    `pins/api.py`에는 아직 사용자 단위 일괄 삭제 함수가 없고, `recommend`는 `evidence_lines`
    테이블 자체를 아직 만들지 않았다(`recommend/models.py` 상단 docstring이 "근거 조립
    세션의 후속 범위"라고 명시). 두 모듈에 필요한 함수가 생기면 이 함수 안에서 호출 두 줄만
    추가하면 된다 — 지금은 이 모듈이 소유한 `users` 행만 지운다."""
    row = get_active_user_or_401(db, user_id=user_id)
    row.deleted_at = datetime.now(timezone.utc)
    db.flush()
    return row
