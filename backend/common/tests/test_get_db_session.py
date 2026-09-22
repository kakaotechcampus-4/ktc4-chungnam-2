"""common/database.py::get_db_session 회귀 테스트 (#101, PR #94 멘토 리뷰 포인트 2).

이전엔 maps/pins/shortlist/auth가 각자 `def get_db_session(): yield from get_db()`를
복붙해뒀고(authz는 그중 maps 걸 가져다 씀). 몸통이 같아도 FastAPI의 의존성 캐시는 함수
"객체" 동일성으로 재사용 여부를 판단하므로, 한 요청 안에서 서로 다른 모듈의 get_db_session이
같이 걸리면(예: pins 라우터 + authz.guard의 멤버십 확인, 또는 auth.get_current_user + 다른
모듈 라우터) DB 세션이 2개 열려 "요청 하나 = 트랜잭션 하나"가 깨졌다. 이제 공용
`common.database.get_db_session` 하나만 있고 각 모듈은 재노출만 한다 — 이 파일은 그 결과를
확인한다: (1) 다섯 모듈이 진짜 같은 함수 객체를 쓰는지, (2) 한 요청 안에서 그 함수가 여러 번
Depends로 걸려도 세션 인스턴스가 하나만 생기는지(FastAPI의 요청 스코프 의존성 캐싱).

PostGIS/Postgres가 안 떠 있어도 통과한다 — 세션을 실제로 쓰지(query/flush) 않으면 커밋도
연결을 필요로 하지 않는다(SQLAlchemy 세션은 첫 사용 시점에야 커넥션을 연다)."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from common.database import get_db_session


def test_five_modules_reexport_the_same_function_object():
    """maps/pins/shortlist/authz/auth의 deps.py가 각자 정의를 두지 않고 재노출만 하는지 —
    함수 객체 동일성이 곧 "FastAPI 의존성 캐시가 하나로 합친다"는 보장이다."""
    from auth.deps import get_db_session as auth_get_db_session
    from authz.deps import get_db_session as authz_get_db_session
    from maps.deps import get_db_session as maps_get_db_session
    from pins.deps import get_db_session as pins_get_db_session
    from shortlist.deps import get_db_session as shortlist_get_db_session

    assert maps_get_db_session is get_db_session
    assert pins_get_db_session is get_db_session
    assert shortlist_get_db_session is get_db_session
    assert authz_get_db_session is get_db_session
    assert auth_get_db_session is get_db_session


def test_one_request_opens_exactly_one_session():
    """실제 요청 하나를 태워, 서로 다른 두 Depends(get_db_session) 지점(예: 라우터 자체의
    DB 의존성과 authz 멤버십 게이트웨이가 쓰는 DB 의존성에 해당)이 같은 Session 인스턴스를
    받는지 확인한다. 세션이 둘이면 한쪽 커밋을 다른 쪽이 트랜잭션 격리로 못 보는 문제가
    생긴다(PR #94 멘토 리뷰 포인트 2) — 이 테스트가 그 회귀를 잡는다."""
    app = FastAPI()

    @app.get("/probe")
    def probe(
        db_a: Session = Depends(get_db_session),
        db_b: Session = Depends(get_db_session),
    ):
        return {"same_session": db_a is db_b}

    with TestClient(app) as client:
        response = client.get("/probe")

    assert response.status_code == 200
    assert response.json() == {"same_session": True}
