"""FastAPI 의존성 배선 — DB 세션만(backend/maps/deps.py와 같은 패턴)."""

from fastapi import Depends

from common.database import get_db_session

DbSession = Depends(get_db_session)
