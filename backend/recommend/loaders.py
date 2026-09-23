"""
authz.guard.require()/require_with_principal()가 쓸 리소스 로더(pins/loaders.py·
shortlist/loaders.py와 같은 패턴). run 하위 엔드포인트(evidence/regions/execute/result/widen/
retry)는 URL에 mapId가 없어(runId만 있다) require_map_member()/require_on_map()을 그대로
못 쓴다 — 이 로더가 run을 읽어 Resource.map_id를 채워 넘긴다.

이 로더 하나를 액션 두 개가 나눠 쓴다(recommend/router.py의 RunGate/EvidenceGate) —
"recommend.manage"(지역확인·실행·결과조회·반경넓히기·재시도, run.requested_by 본인만·가드레일1)와
"recommend.evidence"(근거 조회·토글·추가, 지도 구성원 누구나·#32 결정 2026-09-23 — "근거 목록은
구성원별로 한 줄씩 따로 뜬다"). resource.author_id=run.requested_by는 두 액션 모두에 채워
넘기지만, AUTHOR_CONSTRAINED_ACTIONS에 "recommend.manage"만 있어 실제로 좁혀지는 건 그쪽뿐이다
(authz/core.py 3단계). resource.type="map"으로 채우는 이유: authz/policy.py의
ACTION_RESOURCE_TYPES가 두 액션 모두 frozenset({"map"})으로 선언해뒀기 때문 — "candidate"/"run"
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
