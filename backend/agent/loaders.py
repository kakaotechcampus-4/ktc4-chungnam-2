"""
authz.guard.require_with_principal()이 쓸 리소스 로더(pins/loaders.py, shortlist/loaders.py와 같은 패턴).

지도 제안은 지도에 딸린다 — 제안 id로 읽은 행의 map_id로 Resource(type="map")를 만든다(authz/policy.py의
agent.* 액션은 map 리소스, Rule A: 경로가 아니라 읽은 행에서). 없는 제안과 shadow 제안은 여기서 404로 끝낸다 —
shadow는 화면에 없는 것처럼 다룬다(명세 15절, 17절 15번). 그 뒤 authz.guard가 비구성원 404, 구성원 액션 판정을 한다.
"""

from dataclasses import dataclass

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from agent import service
from agent.deps import get_db_session
from agent.models import AgentSuggestion
from authz.core import Resource
from common.errors import AppError


@dataclass(frozen=True)
class LoadedSuggestion:
    resource: Resource
    obj: AgentSuggestion


def load_suggestion(suggestionId: str = Path(...), db: Session = Depends(get_db_session)) -> LoadedSuggestion:
    row = service.get_suggestion(db, suggestionId)
    if row is None or row.shadow:
        raise AppError("NOT_FOUND")
    return LoadedSuggestion(resource=Resource(type="map", map_id=row.map_id), obj=row)
