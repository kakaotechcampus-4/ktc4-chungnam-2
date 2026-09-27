"""
공유 DB 엔진/세션/Base. 모듈별 models.py가 여기 Base를 상속해서 테이블을 정의한다
(docs/data-model.md — 각 모듈은 자신이 소유한 테이블만 정의).
"""

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from common.settings import settings

DATABASE_URL = settings.database_url   # 이름은 그대로 둔다 — 밖에서 import하는 곳이 있을 수 있다

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


@contextmanager
def session_scope(db: Session):
    """get_db와 pins/tests/conftest.py의 오버라이드가 공유하는 커밋/롤백 규칙 —
    한 곳에만 있어야 테스트가 실제 커밋 경로를 그대로 검증한다.

    @contextmanager로 만든 이유(2차 DeepSeek 재검수 지적 반영): 평범한 제너레이터였다면
    `next()`만 호출하고 버리는 식으로 절반만 소비해도 문법 오류 없이 조용히 commit/rollback을
    건너뛸 수 있었다. `@contextmanager`는 `with` 블록을 안 쓰고 `next()`로 잘못 다루면
    `RuntimeError`를 내거나 `__exit__`가 호출되지 않으면 그 자체가 눈에 띄는 실수가 되므로,
    "반드시 끝까지 소비하라"는 규칙을 문서화가 아니라 구조로 강제한다."""
    try:
        yield db
        db.commit()          # 요청 하나 = 트랜잭션 하나. 여기가 유일한 커밋 지점이다.
    except Exception:
        db.rollback()
        raise


def get_db():
    db = SessionLocal()
    try:
        with session_scope(db) as s:
            yield s
    finally:
        db.close()


def get_db_session():
    """FastAPI Depends용 진입점 — get_db와 이름만 다르고 몸통은 같다(#101).

    이전엔 maps/pins/shortlist가 각자 `def get_db_session(): yield from get_db()`를
    복붙해뒀다. 내용이 같아도 FastAPI의 의존성 캐시는 함수 "객체"가 같은지로 재사용 여부를
    판단하므로, 한 요청 안에서 서로 다른 모듈의 get_db_session이 같이 걸리면(예: pins 라우터
    + authz.guard의 멤버십 확인) DB 세션이 2개 열려 "요청 하나 = 트랜잭션 하나"가 깨졌다
    (PR #94 멘토 리뷰 포인트 2). 이제 이 함수 하나만 있고, 각 모듈의 deps.py는 이걸
    재노출(`from common.database import get_db_session`)만 한다 — 그래야 Depends(get_db_session)이
    어느 모듈에서 걸리든 항상 같은 객체라서 세션이 하나로 합쳐진다."""
    yield from get_db()
