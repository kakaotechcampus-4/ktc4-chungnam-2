"""
FastAPI 의존성 배선 — DB 세션만(backend/pins/deps.py·backend/shortlist/deps.py와 같은 패턴).
멤버십 게이트웨이는 여기 두지 않는다 — authz.deps.get_membership_gateway를 다른 모듈이
바꿔 끼우는 건 이 파일이 아니라 maps/api.py::DbMembershipGateway를 통해서다(authz/deps.py는
루트가 적용, maps/for_Root.md 참고). 이 파일에 `get_membership_gateway`라는 이름을 두면
common/tests/test_adapter_assembly.py::test_adapter_factories_go_through_select가 select()
우회로 잡는다 — 애초에 두지 않는다.
"""

from fastapi import Depends

from common.database import get_db_session

DbSession = Depends(get_db_session)
