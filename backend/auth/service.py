"""
셸 — DB·카카오 HTTP 호출만 여기 둔다. 판정 로직(토큰 서명/검증, 표시 이름 추출)은
auth/core.py(순수 함수)에 있다(docs/code-quality.md 기능형 코어/명령형 셸 분리).

각 함수는 커밋하지 않는다 — common.database.get_db(session_scope)가 요청당 한 번 커밋한다
(pins/api.py와 같은 규약).
"""

from datetime import datetime, timezone

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import core
from auth.models import User
from common.errors import AppError
from common.settings import settings
from maps import api as maps_api
from pins import api as pins_api
from recommend import api as recommend_api

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USERINFO_URL = "https://kapi.kakao.com/v2/user/me"
_HTTP_TIMEOUT_SECONDS = 5.0
_USER_IDENTITY_CONSTRAINT = "uq_users_provider_identity"


class KakaoApiError(AppError):
    """카카오 토큰 교환·프로필 조회가 실패했다 — 상태 코드, 네트워크 오류, 응답 모양이 기대와 다른 경우 모두.
    콜백이 `login_error=kakao_failed`로 돌려보내려고 다른 AppError(탈퇴 계정 등)와 구분한다.
    응답 본문·토큰은 메시지·detail·로그 어디에도 넣지 않는다 — 실패 종류(`reason`)만."""

    def __init__(self, message: str, *, reason: str, kakao_status: int | None = None):
        detail = {"reason": reason}
        if kakao_status is not None:
            detail["kakao_status"] = kakao_status
        super().__init__("UNAUTHORIZED", message, detail=detail)


def _kakao_request(send, *, message: str) -> dict:
    """카카오 HTTP 호출 한 번 — 200이 아니거나, 연결에 실패하거나, JSON 객체가 아니면 KakaoApiError."""
    try:
        resp = send()
    except httpx.HTTPError as exc:
        raise KakaoApiError(message, reason=type(exc).__name__) from None   # 요청 URL·헤더가 든 예외 본문은 버린다
    if resp.status_code != 200:
        raise KakaoApiError(message, reason="http_status", kakao_status=resp.status_code)
    try:
        body = resp.json()
    except ValueError:
        raise KakaoApiError(message, reason="invalid_json") from None
    if not isinstance(body, dict):
        raise KakaoApiError(message, reason="unexpected_shape")
    return body


def _exchange_kakao_code(code: str) -> str:
    """인가 코드 → 액세스 토큰. 실패를 조용히 삼키지 않는다 — OAuth 콜백 실패가 로그인
    성공처럼 처리되면 안 된다(auth/CLAUDE.md "코드 품질" 절)."""
    body = _kakao_request(
        lambda: httpx.post(
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
        ),
        message="카카오 인증에 실패했습니다",
    )
    token = body.get("access_token")
    if not isinstance(token, str) or not token:
        raise KakaoApiError("카카오 인증에 실패했습니다", reason="missing_access_token")
    return token


def _fetch_kakao_profile(access_token: str) -> dict:
    body = _kakao_request(
        lambda: httpx.get(
            KAKAO_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_HTTP_TIMEOUT_SECONDS,
        ),
        message="카카오 사용자 정보를 가져오지 못했습니다",
    )
    if body.get("id") is None:
        raise KakaoApiError("카카오 사용자 정보를 가져오지 못했습니다", reason="missing_user_id")
    return body


def _find_user(db: Session, *, provider: str, provider_user_id: str) -> User | None:
    return db.execute(
        select(User).where(User.provider == provider, User.provider_user_id == provider_user_id)
    ).scalar_one_or_none()


def _reject_if_withdrawn(row: User) -> User:
    if row.deleted_at is not None:
        # 탈퇴한 계정으로 재로그인 — 조용히 되살리지 않는다. 재활성화를 허용할지는
        # 12절 범위 밖의 별도 결정이라 지금은 막고 루트에 보고한다(auth/for_Root.md).
        raise AppError("UNAUTHORIZED", "탈퇴한 계정입니다")
    return row


def find_or_create_user(db: Session, *, provider: str, provider_user_id: str, display_name: str) -> User:
    """같은 카카오 계정의 첫 로그인이 동시에 두 번 들어오면 둘 다 "없다"고 보고 INSERT한다 —
    유일 제약(uq_users_provider_identity)이 계정 분열은 막지만, 나중 요청의 위반을 안 잡으면
    500이 된다. 세이브포인트 안에서 넣어 보고, 그 제약 위반이면 먼저 만들어진 행을 다시 읽어
    돌려준다(shortlist.service.add_item과 같은 세이브포인트 패턴 — 단, add를 세이브포인트 안에서 해서
    위반이 세이브포인트 안에서 터지므로 세션 전체를 db.rollback()할 필요가 없다). 오류 코드와 제약 이름을 함께 확인해서 다른 무결성 오류는 삼키지 않는다."""
    row = _find_user(db, provider=provider, provider_user_id=provider_user_id)
    if row is not None:
        return _reject_if_withdrawn(row)
    row = User(provider=provider, provider_user_id=provider_user_id, display_name=display_name)
    try:
        with db.begin_nested():
            db.add(row)   # 세이브포인트 안에서 add한다 — 밖에서 add하면 begin_nested() 진입 시 autoflush가 먼저 터진다
            db.flush()
    except IntegrityError as exc:
        if getattr(exc.orig, "pgcode", None) == "23505" and _USER_IDENTITY_CONSTRAINT in str(exc.orig):
            existing = _find_user(db, provider=provider, provider_user_id=provider_user_id)
            if existing is not None:
                return _reject_if_withdrawn(existing)
        raise
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


def update_display_name(db: Session, *, user_id: str, display_name: str) -> User:
    """계정 단위 표시 이름 수정 — 모든 지도에 같은 이름이 보인다(지도별 이름은 없다)."""
    row = get_active_user_or_401(db, user_id=user_id)
    row.display_name = display_name
    db.flush()
    return row


def revoke_sessions(db: Session, *, user_id: str) -> None:
    """로그아웃 — 지금까지 발급된 모든 세션 토큰을 무효화한다(쿠키 삭제만으로는 이미 복사된
    토큰이 살아있다). UPDATE라 행이 없어도(dev 스텁 사용자) 실패하지 않는다."""
    db.execute(update(User).where(User.id == user_id).values(sessions_valid_after=datetime.now(timezone.utc)))


def withdraw_user(db: Session, *, user_id: str) -> User:
    """탈퇴 처리(12절, #155) — users 행은 soft delete, 그 사람의 반응·근거 줄은 삭제한다.

    방장인 지도는 먼저 후임에게 넘기고, 넘길 사람이 없으면 지도를 삭제한다(#369 10번). 탈퇴자의
    멤버십 행은 남는다(#245) — 핀 작성자 표시에 쓴다.

    반응·근거 줄·멤버십은 다른 모듈 테이블이라 각 모듈의 공개 함수(api.py)로만 바꾼다. 핀·확정 리스트
    항목은 남고, 작성자 표시는 auth.api.display_names가 "탈퇴한 구성원"으로 내려준다.
    모든 쓰기는 같은 트랜잭션이라 중간에 실패하면 함께 롤백된다."""
    row = get_active_user_or_401(db, user_id=user_id)
    maps_api.transfer_or_delete_owned_maps(db, user_id)
    pins_api.delete_reactions_by_user(db, user_id=user_id)
    recommend_api.delete_evidence_lines_by_author(db, user_id=user_id)
    row.deleted_at = datetime.now(timezone.utc)
    db.flush()
    return row
