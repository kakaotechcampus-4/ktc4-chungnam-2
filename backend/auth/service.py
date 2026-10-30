"""
셸 — DB·카카오 HTTP 호출만 여기 둔다. 판정 로직(토큰 서명/검증, 표시 이름 추출)은
auth/core.py(순수 함수)에 있다(docs/code-quality.md 기능형 코어/명령형 셸 분리).

각 함수는 커밋하지 않는다 — common.database.get_db(session_scope)가 요청당 한 번 커밋한다
(pins/api.py와 같은 규약).
"""

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import exists, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agent import api as agent_api
from auth import core
from auth.models import IDENTITY_CONSTRAINT, User, UserIdentity
from common.errors import AppError
from common.settings import settings
from maps.schemas import Map
from feedback import api as feedback_api
from llm import api as llm_api
from maps import api as maps_api
from notifications import api as notifications_api
from pins import api as pins_api
from recommend import api as recommend_api
from shortlist import api as shortlist_api

logger = logging.getLogger(__name__)

KAKAO_TOKEN_URL = "https://kauth.kakao.com/oauth/token"
KAKAO_USERINFO_URL = "https://kapi.kakao.com/v2/user/me"
_HTTP_TIMEOUT_SECONDS = 5.0


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
    """그 로그인 수단의 사용자."""
    return db.execute(
        select(User).join(UserIdentity, UserIdentity.user_id == User.id)
        .where(UserIdentity.provider == provider, UserIdentity.provider_user_id == provider_user_id)
    ).scalar_one_or_none()


def _reject_if_withdrawn(row: User) -> User:
    if row.deleted_at is not None:
        # 탈퇴한 계정으로 재로그인 — 되살리지 않고 막는다(docs/data-model.md auth 절, #409).
        raise AppError("UNAUTHORIZED", "탈퇴한 계정입니다")
    return row


def _is_identity_conflict(exc: IntegrityError) -> bool:
    """그 로그인 수단이 이미 다른 사용자에 있다(unique(provider, provider_user_id) 위반). 다른 무결성 오류는 아니다."""
    return getattr(exc.orig, "pgcode", None) == "23505" and IDENTITY_CONSTRAINT in str(exc.orig)


def find_or_create_user(db: Session, *, provider: str, provider_user_id: str, display_name: str) -> User:
    """로그인 수단으로 사용자를 찾고, 없으면 사용자와 수단을 한 세이브포인트에서 함께 만든다(#694).

    같은 카카오 계정의 첫 로그인이 동시에 두 번 들어오면 둘 다 "없다"고 보고 INSERT한다 —
    유일 제약(IDENTITY_CONSTRAINT)이 계정 분열은 막지만, 나중 요청의 위반을 안 잡으면
    500이 된다. 세이브포인트 안에서 넣어 보고, 그 제약 위반이면 먼저 만들어진 사용자를 다시 읽어
    돌려준다(shortlist.service.add_item과 같은 세이브포인트 패턴 — 단, add를 세이브포인트 안에서 해서
    위반이 세이브포인트 안에서 터지므로 세션 전체를 db.rollback()할 필요가 없다). 세이브포인트가 되돌아가면
    함께 만든 users 행도 사라진다. 오류 코드와 제약 이름을 함께 확인해서 다른 무결성 오류는 삼키지 않는다."""
    row = _find_user(db, provider=provider, provider_user_id=provider_user_id)
    if row is not None:
        return _reject_if_withdrawn(row)
    row = User(display_name=display_name)
    try:
        with db.begin_nested():
            db.add(row)   # 세이브포인트 안에서 add한다 — 밖에서 add하면 begin_nested() 진입 시 autoflush가 먼저 터진다
            db.flush()
            db.add(UserIdentity(user_id=row.id, provider=provider, provider_user_id=provider_user_id))
            db.flush()
    except IntegrityError as exc:
        if _is_identity_conflict(exc):
            existing = _find_user(db, provider=provider, provider_user_id=provider_user_id)
            if existing is not None:
                return _reject_if_withdrawn(existing)
        raise
    return row


def _kakao_identity(code: str) -> tuple[str, str]:
    """인가 코드 → (카카오 사용자 id, 표시 이름)."""
    access_token = _exchange_kakao_code(code)
    profile = _fetch_kakao_profile(access_token)
    return str(profile["id"]), core.display_name_from_kakao_profile(profile)


def login_with_kakao_code(db: Session, *, code: str) -> User:
    provider_user_id, display_name = _kakao_identity(code)
    return find_or_create_user(db, provider="kakao", provider_user_id=provider_user_id, display_name=display_name)


def login_guest_with_kakao_code(db: Session, *, code: str, guest_user_id: str) -> tuple[User, bool | None]:
    """게스트 세션으로 시작한 카카오 로그인(#560, #694). (로그인할 사용자, guest_merged)를 돌려준다."""
    provider_user_id, display_name = _kakao_identity(code)
    return claim_guest(
        db, guest_user_id=guest_user_id, provider="kakao", provider_user_id=provider_user_id, display_name=display_name,
    )


def create_qa_user(db: Session, *, display_name: str) -> User:
    """스테이징 전용 QA 로그인(#788) — 부를 때마다 새 사용자와 로그인 수단(provider='qa', 새 uuid)을 만든다.
    수단이 있으니 게스트가 아니다. 카카오 첫 로그인과 같은 생성 경로를 쓴다."""
    return find_or_create_user(db, provider="qa", provider_user_id=str(uuid.uuid4()), display_name=display_name)


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


# 탈퇴(#155)에서 그 사람의 기록을 다루는 모듈 단계. (모듈 이름, fn(db, user_id, map_ids)) — 이 순서로 부른다.
# 합치기(MERGE_STEPS)와 짝이다: 여기 있는 모듈은 합치기에도 있어야 한다(#694, test_withdraw_steps_are_also_merge_steps).
# 모듈 api는 호출 시점에 찾는다(테스트가 모듈 함수를 바꿔 끼운다).
WITHDRAW_STEPS = (
    # 방장인 지도는 후임에게 넘기고, 넘길 사람이 없으면 지도를 삭제한다(#369 10번). 탈퇴자의 멤버십 행은 남는다(#245)
    ("maps", lambda db, user_id, map_ids: maps_api.transfer_or_delete_owned_maps(db, user_id)),
    ("pins", lambda db, user_id, map_ids: pins_api.delete_reactions_by_user(db, user_id=user_id)),
    ("recommend", lambda db, user_id, map_ids: recommend_api.delete_evidence_lines_by_author(db, user_id=user_id)),
    # 그 사람의 열람 기록과 잠근 지도들의 요약(docs/agent-v2.md 12.9, #512), 코스 요청 한 줄과 결과(#334)
    ("agent", lambda db, user_id, map_ids: agent_api.delete_by_user(db, user_id=user_id, map_ids=map_ids)),
    ("agent", lambda db, user_id, map_ids: agent_api.delete_course_runs_by_user(db, user_id=user_id)),
    ("feedback", lambda db, user_id, map_ids: feedback_api.anonymize_by_user(db, user_id=user_id)),
    ("notifications", lambda db, user_id, map_ids: notifications_api.delete_by_user(db, user_id=user_id)),
    # 모델 호출 사용량(#870)은 행을 남기고 user_id만 비운다 — 비용 통계는 사람 없이도 쓴다
    ("llm", lambda db, user_id, map_ids: llm_api.anonymize_by_user(db, user_id=user_id)),
)


def withdraw_user(db: Session, *, user_id: str) -> User:
    """탈퇴 처리(12절, #155) — users 행은 soft delete, 그 사람의 반응·근거 줄은 삭제하고 피드백은 작성자 연결만 끊는다(#10).
    로그인 수단(user_identities)은 지우지 않는다 — 같은 카카오 계정의 재로그인을 막는 근거다(#409).

    반응·근거 줄·멤버십은 다른 모듈 테이블이라 각 모듈의 공개 함수(api.py)로만 바꾼다(WITHDRAW_STEPS). 핀·확정 리스트
    항목은 남고, 작성자 표시는 auth.api.display_names가 "탈퇴한 구성원"으로 내려준다.
    모든 쓰기는 같은 트랜잭션이라 중간에 실패하면 함께 롤백된다.

    맨 먼저 속한 지도 행을 id 순서로 잠근다(#435) — 같은 지도의 나가기·양도와 줄을 세워 서로 어긋난
    상태를 보지 않게 하고, 순서가 고정이라 교착도 없다. 잠근 지도 목록은 agent 정리에 그대로 넘긴다(#512)."""
    map_ids = maps_api.lock_member_maps(db, user_id)
    row = get_active_user_or_401(db, user_id=user_id)
    for _, step in WITHDRAW_STEPS:
        step(db, user_id, map_ids)
    row.deleted_at = datetime.now(timezone.utc)
    db.flush()
    return row


def join_as_guest(db: Session, *, display_name: str, invite_token: str) -> tuple[User, Map]:
    """게스트 계정을 만들고 초대 토큰의 지도에 구성원으로 넣는다(#472) — 한 트랜잭션, 커밋은 호출자.
    게스트는 로그인 수단 없이 users 행만 만든다(#694). 상한은 그 토큰으로 만든 게스트 중 아직 수단이 없는 사람만 센다.
    순서: 토큰 검증(404·410) → 게스트 수 확인(409) → 계정 생성 → 지도 가입. 어느 단계든 실패하면 같이 롤백된다.
    같은 토큰의 동시 호출이 상한을 넘기지 않게 토큰 단위 advisory lock을 잡는다."""
    maps_api.check_invite(db, invite_token)
    db.execute(text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"guest_invite:{invite_token}"})
    issued = db.execute(
        select(func.count()).select_from(User).where(User.guest_invite_token == invite_token, User.is_guest)
    ).scalar_one()
    if issued >= core.GUEST_LIMIT_PER_INVITE:
        raise AppError("GUEST_LIMIT")
    row = User(display_name=display_name, guest_invite_token=invite_token, last_seen_at=datetime.now(timezone.utc))
    db.add(row)
    db.flush()
    return row, maps_api.accept_invite(db, token=invite_token, user_id=row.id)


def purge_inactive_guests(db: Session, *, now: datetime, older_than_days: int) -> int:
    """마지막으로 쓴 지 older_than_days일이 지난 게스트를 일반 탈퇴와 같은 규칙으로 지운다(withdraw_user).
    last_seen_at이 없으면 created_at 기준. 이미 탈퇴한 계정은 건너뛴다. 지운 수를 돌려준다."""
    cutoff = now - timedelta(days=older_than_days)
    ids = db.execute(
        select(User.id).where(
            User.is_guest, User.deleted_at.is_(None),
            func.coalesce(User.last_seen_at, User.created_at) < cutoff,
        ).order_by(User.id)
    ).scalars().all()
    for user_id in ids:
        withdraw_user(db, user_id=user_id)
    return len(ids)


# 게스트 → 카카오 합치기(#560). 각 모듈이 자기 테이블만 옮기는 `<module>.api.reassign_user(db, *, from_user_id, to_user_id)`를
# 이 순서로 부른다(docs/data-model.md「게스트 전환과 합치기」). 이미 쓰던 카카오 계정이 있을 때만 탄다 — 처음 쓰는 카카오
# 계정이면 게스트 행에 수단을 붙이고 끝이다(#694). 모듈 api는 호출 시점에 찾는다 — 그 함수가 없는 모듈은
# AttributeError로 실패해 합치기 전체가 롤백되고 게스트 기록이 남는다(일부만 옮긴 채 게스트를 지우는 일은 없다).
# 탈퇴(WITHDRAW_STEPS)에 있는 모듈은 여기에도 있어야 한다.
MERGE_STEPS = (
    ("maps", maps_api),
    ("pins", pins_api),
    ("recommend", recommend_api),
    ("shortlist", shortlist_api),
    ("notifications", notifications_api),
    ("feedback", feedback_api),
    ("agent", agent_api),
    ("llm", llm_api),
)


def live_guest_id_for_session(db: Session, session_cookie: str | None) -> str | None:
    """로그인 시작 요청에 붙은 세션 쿠키가 지금 유효한 게스트의 것이면 그 user_id, 아니면 None.
    get_current_user와 같은 판정(서명·만료·탈퇴·로그아웃 무효화)이지만 실패해도 예외 대신 None —
    로그인 시작은 게스트가 아닌 사람도 하는 경로다."""
    if not session_cookie:
        return None
    claims = core.parse_session_token(session_cookie, secret=settings.session_secret, now=int(time.time()))
    if claims is None:
        return None
    row = db.get(User, claims.user_id)
    if row is None or row.deleted_at is not None or not row.is_guest:
        return None
    if core.is_revoked(claims.issued_at, row.sessions_valid_after):
        return None
    return row.id


def _lock_live_guest(db: Session, guest_user_id: str) -> User | None:
    """게스트 행을 FOR UPDATE로 잠그고, 잠근 뒤에도 살아 있는 게스트(탈퇴·합쳐짐 아님, 로그인 수단 없음)면 돌려준다.
    같은 게스트로 겹친 콜백은 여기서 줄을 선다. 수단은 잠근 뒤 따로 읽는다 — 잠금을 기다린 SELECT의 하위 질의
    (User.is_guest)는 잠금 전 스냅숏을 봐서, 앞 요청이 방금 붙인 수단을 못 본다."""
    guest = db.execute(
        select(User).where(User.id == guest_user_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if guest is None or guest.deleted_at is not None:
        return None
    if db.execute(select(exists().where(UserIdentity.user_id == guest_user_id))).scalar_one():
        return None
    return guest


def _attach_identity_to_guest(db: Session, *, guest_user_id: str, provider: str, provider_user_id: str) -> User | None:
    """처음 쓰는 로그인 수단을 게스트 행에 붙인다 — 사용자 id·표시 이름 그대로, guest_invite_token은 비운다(초대당
    상한에서 빠진다). 다른 모듈은 부르지 않는다. 붙였으면 그 사용자, 살아 있는 게스트가 아니거나 같은 수단이 방금 다른
    사용자에 붙었으면(유일 제약) None. 세이브포인트 안이라 실패하면 붙이던 쓰기만 되돌아간다."""
    guest = _lock_live_guest(db, guest_user_id)
    if guest is None:
        return None
    try:
        with db.begin_nested():
            db.add(UserIdentity(user_id=guest.id, provider=provider, provider_user_id=provider_user_id))
            guest.guest_invite_token = None
            db.flush()
    except IntegrityError as exc:
        if _is_identity_conflict(exc):
            return None
        raise
    db.expire(guest, ["is_guest"])
    return guest


def claim_guest(
    db: Session, *, guest_user_id: str, provider: str, provider_user_id: str, display_name: str,
) -> tuple[User, bool | None]:
    """게스트가 시작한 로그인(#694, docs/data-model.md「게스트 전환과 합치기」). (로그인할 사용자, guest_merged)를 돌려준다.

    - 그 수단이 처음이면 게스트 행에 붙인다 → (게스트, True)
    - 이미 그 수단의 사용자가 있으면 게스트 기록을 그 사용자로 합친다 → (그 사용자, merge_guest_into 결과).
      같은 수단이 동시에 다른 게스트에 붙어 유일 제약에 걸린 쪽도 여기로 온다
    - 그 수단의 사용자가 이 게스트 자신이면(같은 게스트로 겹친 콜백에서 앞 요청이 이미 붙였다) → (게스트, True)
    - 게스트가 아니면(이미 합쳐짐·탈퇴) 보통 로그인과 같고 guest_merged는 None

    붙이기가 예상 밖으로 실패하면 보통 로그인으로 사용자를 찾거나 만들고 False — 카카오 로그인은 성공이고 게스트 기록은
    남는다. 탈퇴한 카카오 계정은 지금처럼 막는다(#409, AppError). 커밋하지 않는다."""
    def login() -> User:
        return find_or_create_user(db, provider=provider, provider_user_id=provider_user_id, display_name=display_name)

    existing = _find_user(db, provider=provider, provider_user_id=provider_user_id)
    if existing is not None:
        _reject_if_withdrawn(existing)
    else:
        try:
            attached = _attach_identity_to_guest(
                db, guest_user_id=guest_user_id, provider=provider, provider_user_id=provider_user_id,
            )
        except Exception as exc:  # noqa: BLE001 — 붙이기 실패가 카카오 로그인 성공을 막으면 안 된다
            logger.error("guest attach failed: error=%s", type(exc).__name__)
            return login(), False
        if attached is not None:
            return attached, True
        existing = login()
    if existing.id == guest_user_id:
        return existing, True
    return existing, merge_guest_into(db, guest_user_id=guest_user_id, to_user_id=existing.id)


def merge_guest_into(db: Session, *, guest_user_id: str, to_user_id: str) -> bool | None:
    """게스트 기록을 이미 쓰던 카카오 계정으로 합친다(claim_guest가 부른다).

    None — 합칠 대상이 아니다(자기 자신, 게스트 행이 없거나 게스트가 아니거나 이미 지워짐). 이미 합쳐진 게스트 id로
    다시 오면 여기로 온다.
    True — 모든 모듈 단계와 게스트 행 삭제(deleted_at)가 끝났다.
    False — 어느 단계든 실패했다. 합치기는 세이브포인트 안이라 그 안의 쓰기만 롤백되고 카카오 로그인은
    유지된다. 로그에는 단계 이름과 에러 종류만 남긴다(메시지에 사용자 데이터가 섞일 수 있다).
    커밋하지 않는다 — 요청당 한 번 커밋은 get_db 몫이다."""
    if guest_user_id == to_user_id:
        return None
    step = "lookup"
    try:
        # 같은 게스트로 두 콜백이 겹쳐도 한쪽만 옮기게 행을 잠그고, 잠근 뒤에 살아 있는 게스트인지 확인한다.
        guest = _lock_live_guest(db, guest_user_id)
        if guest is None:
            return None
        with db.begin_nested():
            for step, module_api in MERGE_STEPS:
                module_api.reassign_user(db, from_user_id=guest_user_id, to_user_id=to_user_id)
            step = "auth"
            guest.deleted_at = datetime.now(timezone.utc)
            db.flush()
    except Exception as exc:  # noqa: BLE001 — 합치기 실패가 카카오 로그인 성공을 막으면 안 된다
        logger.error("guest merge failed: step=%s error=%s", step, type(exc).__name__)
        return False
    return True
