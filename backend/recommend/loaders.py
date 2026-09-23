"""
authz.guard.require()/require_with_principal()가 쓸 리소스 로더(pins/loaders.py·
shortlist/loaders.py와 같은 패턴). run 하위 엔드포인트(evidence/regions/execute/result/widen/
retry)는 URL에 mapId가 없어(runId만 있다) require_map_member()/require_on_map()을 그대로
못 쓴다 — 이 로더가 run을 읽어 Resource.map_id를 채워 넘긴다.

action="recommend.manage"를 이 로더를 쓰는 모든 엔드포인트에 재사용한다 — evidence 조회·토글·
지역확인·실행·결과조회·반경넓히기·재시도 전부 "그 run을 요청한 본인만"이라는 같은 제약을
받는다(가드레일1, 루트 확정 2026-09-23). resource.author_id=run.requested_by를 채워야
AUTHOR_CONSTRAINED_ACTIONS 검사가 실제로 작동한다 — 여기서 빠뜨리면 authz/core.py의 3단계
검사가 통째로 무력화된다. resource.type="map"으로 채우는 이유: authz/policy.py의
ACTION_RESOURCE_TYPES["recommend.manage"] == frozenset({"map"})이기 때문 — "candidate"/"run"
같은 새 타입을 쓰면 이 액션과 타입이 안 맞아 can()이 항상 False가 된다(authz/core.py 2단계
"액션-리소스 종류 결합" 검사).
"""

from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Path
from sqlalchemy.orm import Session

from authz.core import Resource
from common.database import get_db_session
from recommend import service


@dataclass(frozen=True)
class LoadedRun:
    resource: Resource
    obj: Any  # recommend.models.RecommendRun


def load_run(runId: str = Path(...), db: Session = Depends(get_db_session)) -> LoadedRun:
    run = service.get_run_or_404(db, runId)
    return LoadedRun(resource=Resource(type="map", map_id=run.map_id, author_id=run.requested_by), obj=run)
