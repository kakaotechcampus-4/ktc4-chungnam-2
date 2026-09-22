"""
FastAPI 의존성 배선 — DB 세션만(backend/pins/deps.py와 같은 패턴). membership 게이트는
authz.deps.get_membership_gateway를 그대로 가져다 쓴다(shortlist가 자기 것을 새로 만들지
않는다 — authz/CLAUDE.md "가짜 멤버십을 각자 만들지 않는다").
"""

from fastapi import Depends

from common.database import get_db_session

DbSession = Depends(get_db_session)
