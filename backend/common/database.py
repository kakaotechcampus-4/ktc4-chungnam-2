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
