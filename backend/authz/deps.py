"""
FastAPI 의존성 배선. issue #89 — membership에는 더 이상 dev/real 두 구현이 없다. `maps.api.
DbMembershipGateway`가 유일한 구현이고, `AllowAllMembership`(늘 'member') 개발용 스텁과
`MEMBERSHIP_MODE` 포트는 완전히 제거했다 — "선택지가 있어서 잘못 고를 수 있는" 상태 자체를
없앤다(authz/for_Root.md "[루트 정정]" 절 참고, `common.adapters.select()`를 거칠 이유가
없어졌다).

authz는 HTTP 라우터가 없으므로(이 모듈은 다른 모듈이 호출하는 라이브러리다) 여기 배선은 authz
자신의 테스트, 그리고 다른 모듈의 router.py가 가져다 쓰는 용도다. 이름(`get_membership_gateway`,
`MembershipGatewayDep`)은 하위 호환을 위해 그대로 유지한다 — `authz/guard.py`가 이 이름으로
가져다 쓴다. 회귀 방지는 `authz/tests/test_deps.py` 참고(늘 `DbMembershipGateway`로만 풀리고,
"항상 member" 스텁이 다시 안 생기는지 못박는다).
"""

from fastapi import Depends
from sqlalchemy.orm import Session

from authz.ports import MembershipGateway
from common.database import get_db_session
from maps.api import DbMembershipGateway


def get_membership_gateway(db: Session = Depends(get_db_session)) -> MembershipGateway:
    return DbMembershipGateway(db)


MembershipGatewayDep = Depends(get_membership_gateway)
