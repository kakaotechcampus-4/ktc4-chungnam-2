"""
docs/api-spec.yaml의 recommend 태그 엔드포인트 전체(#108 + PR #71 publish_candidate 슬라이스).

인가 요약:
- `GET /maps/{mapId}/recommend/readiness` — require_map_member()(순수 멤버십, mapId가 경로에
  있다).
- `POST /maps/{mapId}/runs` — require_on_map("recommend.request")(실제 액션 판정, mapId가
  경로에 있다).
- run 하위 evidence(GET/PATCH) — recommend/loaders.py::load_run +
  require_with_principal("recommend.evidence", load_run). 지도 구성원 누구나 통과한다(#32 결정,
  2026-09-23: "근거 목록은 구성원별로 한 줄씩 따로 뜬다" — 최종기획안 5-5, 협업적 열람·추가가
  맞다). 개별 근거 줄 비활성화만 그 줄 작성자 본인으로 flows.patch_evidence 내부에서 별도
  제한한다(evidence.disable, author-constrained).
- run 하위 실행계(regions/execute/result/widen/retry) — recommend/loaders.py::load_run +
  require_with_principal("recommend.manage", load_run). mapId가 경로에 없어(runId만) 위 둘을
  못 쓴다. recommend.manage는 run.requested_by 본인만 통과한다(AUTHOR_CONSTRAINED_ACTIONS) —
  가드레일1("대안은 요청한 사람에게만 먼저 보인다") 위반 방지(루트 수정, 2026-09-23 —
  Antigravity 검수로 발견: 이전엔 recommend.request를 재사용해서 아무 구성원이나 남의 run
  결과를 조회·조작할 수 있었다). evidence를 여기서 뺀 이유는 위 항목 참고.
- `POST /candidates/{candidateId}/publish` — flows.publish_candidate 내부에서
  authz.guard.require()를 직접 호출한다(PR #71 결정, Rule A 대응 — flows.py 모듈 docstring 참고).
"""

from fastapi import APIRouter, Depends, Path
from sqlalchemy.orm import Session

from auth.deps import get_current_user
from auth.schemas import CurrentUser
from authz.core import Principal
from authz.deps import MembershipGatewayDep
from authz.guard import require_map_member, require_on_map, require_with_principal
from authz.ports import MembershipGateway
from pins import api as pins_api
from pins.schemas import Pin
from recommend import flows
from recommend.deps import DbSession, PlaceFactsGatewayDep, PlaceSearchGatewayDep
from recommend.loaders import load_run
from recommend.ports import PlaceFactsGateway, PlaceSearchGateway
from recommend.schemas import (
    EvidenceLine,
    EvidencePatchRequest,
    Readiness,
    RecommendResult,
    Region,
    RegionConfirmRequest,
    RunCreateRequest,
)
from recommend.schemas import RecommendRun as RecommendRunResponse

router = APIRouter(tags=["recommend"], dependencies=[Depends(get_current_user)])

RecommendForMap = Depends(require_map_member())
RunToCreate = Depends(require_on_map("recommend.request"))
RunGate = Depends(require_with_principal("recommend.manage", load_run))
EvidenceGate = Depends(require_with_principal("recommend.evidence", load_run))


def _run_response(run) -> RecommendRunResponse:
    return RecommendRunResponse(
        id=str(run.id), map_id=run.map_id, category=run.category, status=run.status, attempt_no=run.attempt_no,
    )


@router.get("/maps/{mapId}/recommend/readiness", response_model=dict[str, Readiness])
def get_readiness(mapId: str = Path(...), _principal: Principal = RecommendForMap, db: Session = DbSession):
    return flows.get_readiness(db, map_id=mapId)


@router.post("/maps/{mapId}/runs", response_model=RecommendRunResponse, status_code=202)
def post_run(body: RunCreateRequest, mapId: str = Path(...), principal: Principal = RunToCreate, db: Session = DbSession):
    run = flows.create_run(db, map_id=mapId, category=body.category, requested_by=principal.user_id)
    return _run_response(run)


@router.get("/runs/{runId}/evidence", response_model=list[EvidenceLine], response_model_exclude_none=True)
def get_evidence(gated=EvidenceGate, db: Session = DbSession):
    run, principal = gated
    return flows.list_evidence(db, run_id=str(run.id), principal=principal)


@router.patch("/runs/{runId}/evidence", response_model=list[EvidenceLine], response_model_exclude_none=True)
def patch_evidence(body: EvidencePatchRequest, gated=EvidenceGate, db: Session = DbSession):
    run, principal = gated
    return flows.patch_evidence(
        db, run_id=str(run.id), principal=principal,
        toggles=[(t.id, t.is_active) for t in body.toggle], adds=[a.text for a in body.add],
    )


@router.post("/runs/{runId}/regions/confirm", response_model=list[Region])
def post_regions_confirm(body: RegionConfirmRequest, gated=RunGate, db: Session = DbSession):
    run, _principal = gated
    return flows.confirm_regions(db, run_id=str(run.id), accept_union=body.accept_union)


@router.post("/runs/{runId}/execute", response_model=RecommendRunResponse, status_code=202)
def post_execute(
    gated=RunGate, db: Session = DbSession,
    place_search: PlaceSearchGateway = PlaceSearchGatewayDep, place_facts: PlaceFactsGateway = PlaceFactsGatewayDep,
):
    run, _principal = gated
    updated = flows.execute_run(db, run_id=str(run.id), place_search=place_search, place_facts=place_facts)
    return _run_response(updated)


@router.get("/runs/{runId}/result", response_model=RecommendResult, response_model_exclude_none=True)
def get_result(gated=RunGate, db: Session = DbSession):
    run, principal = gated
    return flows.get_result(db, run_id=str(run.id), principal=principal)


@router.post("/runs/{runId}/widen", status_code=202)
def post_widen(
    gated=RunGate, db: Session = DbSession,
    place_search: PlaceSearchGateway = PlaceSearchGatewayDep, place_facts: PlaceFactsGateway = PlaceFactsGatewayDep,
):
    run, _principal = gated
    flows.widen_run(db, run_id=str(run.id), place_search=place_search, place_facts=place_facts)


@router.post("/runs/{runId}/retry", response_model=RecommendRunResponse, status_code=202)
def post_retry(
    gated=RunGate, db: Session = DbSession,
    place_search: PlaceSearchGateway = PlaceSearchGatewayDep, place_facts: PlaceFactsGateway = PlaceFactsGatewayDep,
):
    run, _principal = gated
    updated = flows.retry_run(db, run_id=str(run.id), place_search=place_search, place_facts=place_facts)
    return _run_response(updated)


@router.post("/candidates/{candidateId}/publish", response_model=Pin, response_model_exclude_none=True)
def post_publish(
    candidateId: str = Path(...), user: CurrentUser = Depends(get_current_user),
    membership: MembershipGateway = MembershipGatewayDep, db: Session = DbSession,
):
    pin_row = flows.publish_candidate(db, candidate_id=candidateId, requester_id=user.user_id, membership=membership)
    # publish_candidate가 이미 멤버십을 확인했다 — pins.api.create_ai_pin과 같은 이유로
    # 여기서도 게시자 본인을 member로 간주해 응답 조립용 Principal을 구성한다(중복 조회 없이).
    principal = Principal(user_id=user.user_id, map_id=pin_row.map_id, role="member")
    return pins_api.get_pin_response_for_viewer(db, pin_id=str(pin_row.id), viewer_id=user.user_id, principal=principal)
