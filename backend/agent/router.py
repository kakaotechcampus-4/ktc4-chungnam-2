"""
docs/api-spec.yaml `agent` 태그 — 「핑고 AI 조언」 바텀시트(명세 14절). 에이전트는 아무것도 직접 실행하지 않는다:
accept는 버튼의 동작 설명만 돌려주고 실행은 FE가 손으로 할 때와 같은 API로 한다.

인가는 여기서 분기하지 않는다(authz.guard, docs/permissions.md).
- GET 상태: require_map_member() — 조회는 액션이 아니라 멤버십만
- PUT 모드: require_on_map("agent.toggle")
- 제안 accept·dismiss: require_with_principal("agent.suggestion.resolve", load_suggestion) — 제안 id로 읽은 행의 지도로 판정
- 제안 view: 같은 가드. 열람 전용 액션이 없어(permissions.md "열람 기록과 상태 조회는 구성원이면 된다") 구성원 누구나
  가진 agent.suggestion.resolve로 멤버십을 본다 — pins/router.py PinToRead가 pin.react를 빌리는 것과 같은 사정
비구성원은 404, shadow 제안은 없는 것처럼 404(loaders.py)다.

`/runs/{runId}/advice`(추천 막힘 조언)는 recommend 태그이고 M2다. `/internal/agent/tick`은 #535다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from agent import flows
from agent.deps import DbSession
from agent.loaders import load_suggestion
from agent.schemas import AgentAcceptRequest, AgentAcceptResponse, AgentSettings, AgentSettingsRequest, AgentState
from auth.deps import get_current_user
from authz.core import Principal
from authz.guard import require_map_member, require_on_map, require_with_principal

router = APIRouter(tags=["agent"], dependencies=[Depends(get_current_user)])

AgentForMap = Depends(require_map_member())
ModeToChange = Depends(require_on_map("agent.toggle"))
SuggestionToResolve = Depends(require_with_principal("agent.suggestion.resolve", load_suggestion))
SuggestionToView = Depends(require_with_principal("agent.suggestion.resolve", load_suggestion))


def _now() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/maps/{mapId}/agent", response_model=AgentState)
def get_agent_state(mapId: str = Path(...), principal: Principal = AgentForMap, db: Session = DbSession):
    return flows.get_state(db, map_id=mapId, user_id=principal.user_id, now=_now())


@router.put("/maps/{mapId}/agent/settings", response_model=AgentSettings)
def put_agent_settings(
    body: AgentSettingsRequest, mapId: str = Path(...), principal: Principal = ModeToChange, db: Session = DbSession,
):
    return flows.change_settings(db, map_id=mapId, enabled=body.enabled, user_id=principal.user_id, now=_now())


@router.post("/agent/suggestions/{suggestionId}/view", status_code=204)
def post_suggestion_view(loaded=SuggestionToView, db: Session = DbSession):
    row, principal = loaded
    flows.view(db, row=row, user_id=principal.user_id, now=_now())


@router.post("/agent/suggestions/{suggestionId}/accept", response_model=AgentAcceptResponse)
def post_suggestion_accept(body: AgentAcceptRequest, loaded=SuggestionToResolve, db: Session = DbSession):
    row, principal = loaded
    return flows.accept(db, row=row, action_index=body.action_index, user_id=principal.user_id, now=_now())


@router.post("/agent/suggestions/{suggestionId}/dismiss", status_code=204)
def post_suggestion_dismiss(loaded=SuggestionToResolve, db: Session = DbSession):
    row, principal = loaded
    flows.dismiss(db, row=row, user_id=principal.user_id, now=_now())
