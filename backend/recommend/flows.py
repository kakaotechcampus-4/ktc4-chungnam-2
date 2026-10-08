"""
recommend의 기능 실행 함수 전체 — 다른 모듈 접근(pins.api/maps.api/llm.service/authz/
recommend.ports 게이트웨이)은 전부 이 파일에 둔다(이 모듈 자체 관례 — service.py는 recommend
소유 테이블만, core.py는 순수 판정만). 커밋하지 않는다(common/database.py get_db가 요청당
한 번 커밋한다).

**publish_candidate** — 「지도에 올리기」, mentor-review-plan.md 결정(#71 PR).
**아래 나머지 함수 전부** — #108(코어 파이프라인, llm 스텁 대상 통합) 범위. v1은 실제 비동기
큐가 없어 "202 진행 중"을 문자 그대로 구현하지 않는다 — run 생성·execute·widen·retry 전부
동기로 끝낸다(recommend/for_Root.md에 기록). places(#14)/seeding(#13)이 없어 candidate 풀
확보(PlaceSearchGateway)·라벨 조회(PlaceFactsGateway)는 dev 모드면 recommend/deps.py의 스텁이,
real 모드면 places.api의 자체 DB 함수가 채운다(#190 — 모델 호출은 ② 사유 구조화 하나뿐이다).

**mentor-review-plan.md 대비 실제 구현 차이 (for_Root.md에 자세히 기록, 요약만 여기)**:
계획 문서(작성 09-11 22:46)는 `membership: MembershipGateway`에 `.is_member(map_id, user_id)
-> bool`이 있다고 전제했다 — 이건 `pins/ports.py`가 갖고 있던 옛 Protocol인데, pins의 PR #71
재작업(09-12 00:10~00:24, 계획보다 늦게 끝남)에서 이미 삭제됐다. 그 사이 `docs/permissions.md`
("권한을 어디서 강제하는가" 절, 계약 변경)가 이미 확정한 실제 규칙은 다음과 같다:
  - 비구성원(role=None) → **404 NOT_FOUND** (계획의 403 FORBIDDEN이 아니다 — 존재를 안 흘린다)
  - 구성원이지만 그 액션이 롤에 없음 → **403 FORBIDDEN** (docs/permissions.md는 404/403 두
    값만 규정한다 — 계획의 "AI_PIN_PRIVATE"는 이 문서보다 먼저 쓰인 추측이었다. `recommend.
    publish`는 `candidate.requested_by`(=run.requested_by) 본인만 가능하도록
    authz/policy.py::AUTHOR_CONSTRAINED_ACTIONS에 이미 등록돼 있어 본인이 아니면 403이 된다)
authz/tests/test_rule_a_static.py가 "resolve_principal은 authz.guard 밖에서 직접 호출하지
않는다"(Rule A)를 정적으로 강제한다 — 그래서 여기서 `authz.service.resolve_principal`/
`authz.core.can`을 직접 부르지 않고, `authz.guard.require(action, loader)`가 반환하는
의존성 함수를 그대로 호출한다(FastAPI Depends 없이 이미 읽은 candidate/run으로 직접 채운
`loaded`를 넘긴다 — 라우터가 없는 flow 함수이므로 사전에 없던 사용법이지만 `require()`
자체는 평범한 함수라 이렇게 불러도 Rule A를 어기지 않는다: resolve_principal 호출은 여전히
guard.py 안에서만 일어난다). "멤버십/작성자 확인이 멱등 경로보다 항상 먼저"라는 계획의 핵심
불변식은 그대로 지킨다.

**두 번째 차이 — 이벤트 타입, 근본 수정 완료(루트, 2026-09-23)**: `pins.api.create_ai_pin`이
예전엔 `pins.core.pin_created_event(pin)`를 써서 `type="pin.created"`인 이벤트를 냈다.
`docs/events.md`는 「지도에 올리기」의 타입을 `"pin.published"`로 못박아뒀고 `create_ai_pin`
자신이 "recommend의 후보 게시 전용"이라고 밝히고 있어, 여기서 매번 `type`만 교정해 새
`Event`를 만드는 우회가 있었다. `pins/core.py`에 `pin_published_event`를 추가하고
`create_ai_pin`이 그걸 쓰도록 고쳐서 이 우회를 지웠다 — `mutation.event`를 그대로 쓴다.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from sqlalchemy.orm import Session

from auth.schemas import CurrentUser
from authz.core import Principal, Resource, can
from authz.guard import require
from authz.ports import MembershipGateway
from authz.schemas import Permissions
from common import categories
from common.errors import AppError
from common.events import Event, record_event
from llm import service as llm_service
from pins import api as pins_api
from pins.schemas import Pin
from recommend import constraints, core, schemas, service
from recommend.models import Candidate as CandidateRow
from recommend.models import RecommendRun
from recommend.ports import Circle, PlaceFactsGateway, PlaceSearchGateway
from recommend.schemas import Check


@dataclass(frozen=True)
class _LoadedCandidate:
    """authz.guard.require()가 기대하는 `Loaded` 모양(.resource/.obj)을 흉내낸다 — FastAPI
    라우트가 아니라 이 함수가 직접 부르므로 loader Depends 없이 이미 읽은 candidate로 채운다."""

    resource: Resource
    obj: Any


_require_publish = require("recommend.publish", loader=None)  # loader는 안 쓴다 — loaded를 직접 넘긴다


def _published_pin_response(db: Session, *, pin_id: str, requester_id: str, run: RecommendRun) -> Pin:
    # publish 가드(_require_publish)가 이미 멤버십을 확인했다 — pins.api.create_ai_pin과 같은 이유로
    # 게시자 본인을 member로 간주해 응답 조립용 Principal을 구성한다(중복 조회 없이).
    principal = Principal(user_id=requester_id, map_id=run.map_id, role="member")
    return pins_api.get_pin_response_for_viewer(db, pin_id=pin_id, viewer_id=requester_id, principal=principal)


def publish_candidate(
    db: Session, *, candidate_id: str, requester_id: str, membership: MembershipGateway,
) -> Pin:
    """반환은 게시된 핀의 응답 스키마(pins.schemas.Pin) — ORM 행(pins.models)을 받으면 이 모듈이
    타입을 적으려고 pins.models를 import해야 해서 경계 규칙을 어긴다(#114)."""
    candidate, run = service.load_candidate_with_run(db, candidate_id)  # 1) 404 NOT_FOUND

    try:
        _require_publish(
            loaded=_LoadedCandidate(
                resource=Resource(type="candidate", map_id=run.map_id, author_id=run.requested_by),
                obj=candidate,
            ),
            user=CurrentUser(user_id=requester_id),
            gateway=membership,
        )
    except AppError as error:
        if error.code == "FORBIDDEN":  # 구성원이지만 요청자가 아니다 — 남의 비공개 후보의 존재를 숨긴다(가드레일 1, #255)
            raise AppError("AI_PIN_PRIVATE") from error
        raise
    # 2)+3) 비구성원 404 NOT_FOUND / 구성원인데 본인 요청 아님 404 AI_PIN_PRIVATE
    # ↑ 여기까지 통과해야만 아래로 내려간다 — 순서를 바꾸지 않는다(멤버십/작성자 확인이
    #   멱등 경로·NOT_READY 판정보다 항상 먼저).

    if candidate.published_pin_id is not None:  #    멱등 빠른 경로 — run 상태와 무관하게 항상 통한다
        return _published_pin_response(db, pin_id=str(candidate.published_pin_id), requester_id=requester_id, run=run)
        #    200, 이벤트 없음. get_pin_response_for_viewer가 NOT_FOUND/AI_PIN_PRIVATE를 던지면(핀이 그
        #    사이 삭제됐거나 비공개로 바뀐 극단적 경우) 그대로 전파한다 — 정직한 실패가 낫다.

    core.check_run_ready(run)  # 4) 409 NOT_READY

    mutation = pins_api.create_ai_pin(
        db, map_id=run.map_id, category=run.category, place_id=candidate.place_id,
        lat=candidate.lat, lng=candidate.lng, created_by=requester_id,
        checks=candidate.checks,  # #124/#57 — 게시 시점에 candidate.checks를 pins로 복사(가드레일 5).
        # pins.api.create_ai_pin이 자기 checks 파라미터에서 pins.schemas.Check로 다시 검증한다
        # (경계 검증, pins/api.py 참고) — 여기서는 candidate.checks를 그대로 넘기기만 한다.
        # #158/#177 — 가드레일5(이유·구성원 충족 집계·출처는 게시된 뒤에도 유지)도 같은 방식으로
        # 복사한다. member_fulfillment의 {}는 "집계 없음"이라 None으로 넘긴다.
        reason=candidate.reason,
        member_fulfillment=candidate.member_fulfillment or None,
        place_source=candidate.place_source,
    )  # 5) INSERT pins (레이스 1번 — uq_pins_map_place 위반 시 여기서 PIN_DUPLICATE)
    service.link_published_pin(db, candidate_id=candidate_id, pin_id=str(mutation.pin.id))  # 6) 가드 UPDATE

    # pins.api.create_ai_pin이 이제 pin.published 타입으로 직접 이벤트를 만든다(루트가
    # pins/core.py에 pin_published_event를 추가해 근본 수정 — 예전엔 여기서 type만 교정하는
    # 우회가 있었다).
    record_event(db, mutation.event)  # 7) event_log — mutation과 같은 db 세션, 커밋 전
    return _published_pin_response(db, pin_id=str(mutation.pin.id), requester_id=requester_id, run=run)  # 8) get_db가 커밋


# ============================================================================
# #108 — 코어 파이프라인(llm 스텁 대상 통합)
# ============================================================================

CATEGORIES: tuple[str, ...] = categories.recommendable()  # common/categories.py(#280)
# 기본값 원 반경(m) — 최종기획안.md 248행에 이미 정의돼 있다: "기본 반경(도보 15분에 해당하는
# 거리)". common.geo.WALKING_SPEED_M_PER_MIN(도보 시간 근사 보정계수)으로 환산한다 — 루트
# 검증 중 발견: 이전 버전은 이 스펙을 못 찾고 2000m(약 25분)를 임의로 썼었다. 계산식으로
# 두면 나중에 WALKING_SPEED_M_PER_MIN이 바뀌어도 같이 맞다.
DEFAULT_REGION_RADIUS_M = core.radius_m_for_walk_min(core.DEFAULT_RADIUS_WALK_MIN)  # 15분 * 80m/분 = 1200m


def get_readiness(db: Session, *, map_id: str) -> dict[str, dict]:
    """GET /maps/{mapId}/recommend/readiness (5-4). 카테고리마다 ♥/🚫 의견이 달린 핀이 1곳 이상이면 열린다
    (#360 — 구성원 수와 무관, 혼자 쓰는 지도도 같다)."""
    return {
        category: core.check_readiness(pins_api.count_opinion_pins(db, map_id=map_id, category=category))
        for category in CATEGORIES
    }


def _evidence_from_reaction(reaction: dict) -> dict:
    """반응에 사람이 쓴 글(reason_text)을 llm.schemas.EvidenceLine 생성 가능한 dict로 — ②에 보낼 입력이다.
    fact_key는 None으로 두고 ②가 채운다(값을 지어내지 않는다 — 실격 조건은 확실할 때만 켜져야 한다).
    badge는 반응 종류로 정한다: 🚫(against)는 반드시 사유가 있고(가드레일3) 실격 성격이 강해 required,
    ♥는 preferred로 낮춘다. 칩은 여기로 오지 않는다 — `_evidence_from_chip`(#412)."""
    return {
        "author_id": reaction["user_id"],
        "source": "reaction",
        "text": reaction["reason_text"],
        "badge": "required" if reaction["type"] == "against" else "preferred",
        "fact_key": None,
    }


def _evidence_from_chip(reaction: dict, chip: dict) -> dict:
    """반응에 고른 칩 하나 → 근거 줄 하나(#412). 키와 방향은 docs/constraints.md 칩 표 그대로(pins.api가
    채워 준다)라 ②를 거치지 않는다. 칩은 🚫에만 있고 고른 순간 뜻이 정해지므로 배지는 required, 글은 칩 label이다.
    키 없는 칩(「공통」·옛 값)도 줄은 만든다 — 반대한 구성원으로 센다(#255)."""
    return {
        "author_id": reaction["user_id"],
        "source": "reaction",
        "text": chip["label"],
        "chip_id": chip["chip_id"],
        "badge": "required",
        "fact_key": chip["fact_key"],
        "wants": chip["wants"],
    }


def _reaction_evidence_lines(raw_reactions: list[dict], planned_texts: list[dict]) -> list[dict]:
    """반응마다 글 줄(②를 거친 것, 있을 때만) 다음에 칩 줄을 붙인다(#412) — 한 사람이 한 반응에 남긴 줄이
    붙어 있어야 「−」로 뺄 자기 근거를 찾기 쉽다. planned_texts는 글이 있는 반응 순서 그대로의 ② 결과다."""
    planned = iter(planned_texts)
    lines: list[dict] = []
    for reaction in raw_reactions:
        if reaction["reason_text"] is not None:
            lines.append(next(planned))
        lines.extend(_evidence_from_chip(reaction, chip) for chip in reaction["chips"])
    return lines


def _default_circle_and_anchors(db: Session, *, map_id: str, category: str) -> tuple[Circle, list[tuple[float, float]]]:
    """지역(regions) 기본값 — places가 없어 실제 검색 범위를 스스로 정할 방법이 이것뿐이다:
    그 카테고리 핀들의 중심 좌표 + 고정 반경. 실제 반경 사유(circle_anchor_pin_id 등)가
    구조화되는 순간(모델 확정 이후) 이 기본값은 "사람이 명시하지 않았을 때만" 쓰여야 한다
    (recommend/for_Root.md에 상세 기록). anchor 좌표 목록도 함께 돌려준다 — #112(선호 순위
    3단계)의 "그 무리의 기준 핀들까지 거리 평균" 계산에 그대로 쓰인다(regions.anchor_points에
    저장, for_Root.md 보고)."""
    coordinates = pins_api.get_category_pin_coordinates(db, map_id=map_id, category=category)
    if not coordinates:
        raise AppError("NOT_READY")
    anchors = [(lat, lng) for _, lat, lng in coordinates]
    center_lat = sum(lat for lat, _ in anchors) / len(anchors)
    center_lng = sum(lng for _, lng in anchors) / len(anchors)
    circle = Circle(anchor_lat=center_lat, anchor_lng=center_lng, radius_m=DEFAULT_REGION_RADIUS_M)
    return circle, anchors


def _region_data(circle: Circle, *, label: str, confirmed: bool, anchor_points: list[tuple[float, float]]) -> dict:
    return {
        "signature": core.region_signature([circle]),
        "label": label,
        "center_lat": circle.anchor_lat,
        "center_lng": circle.anchor_lng,
        "radius_m": circle.radius_m,
        "anchor_points": [[lat, lng] for lat, lng in anchor_points],
        "confirmed": confirmed,
        "confirmed_at": datetime.now(timezone.utc) if confirmed else None,
    }


def create_run(db: Session, *, map_id: str, category: str, requested_by: str) -> RecommendRun:
    """POST /maps/{mapId}/runs — run 생성 + 근거 조립(①②) + 기본값 지역 계산까지 한 요청
    안에서 동기로 끝낸다. 순서: 1) 준비 판정(409 NOT_READY) 2) 재시도 상한(#31) 3) run INSERT
    4) 반응 → 근거 구조화(글은 llm.plan_evidence, 칩은 코드 #412) 5) run INSERT → evidence_lines INSERT 6) 기본값
    지역 INSERT. 모델 호출(최대 15초+재시도)이 끝난 뒤에야 INSERT한다(#208) — 그동안 쓰기
    트랜잭션을 열어두지 않고, 모델이 실패하면 run 행이 남지 않는다."""
    readiness = core.check_readiness(pins_api.count_opinion_pins(db, map_id=map_id, category=category))
    if not readiness["ready"]:
        raise AppError("NOT_READY", detail=readiness)

    current_max = service.max_attempt_no_for_requester(db, map_id=map_id, requested_by=requested_by)
    core.check_retry_limit(current_max)  # #31 — 카테고리 무관 개인 단위 카운터가 이미 상한이면 새 run도 막는다

    raw_reactions = pins_api.list_reasoned_reactions(db, map_id=map_id, category=category)
    # ②에는 사람이 쓴 글만 보낸다(#412) — 칩은 키·방향이 정해져 있어 코드가 줄을 만든다. 글이 없으면 ② 호출도 없다.
    text_inputs = [_evidence_from_reaction(r) for r in raw_reactions if r["reason_text"] is not None]
    planned = llm_service.plan_evidence(text_inputs) if text_inputs else []  # ② — 느린 호출이라 run INSERT보다 먼저(#208)
    reaction_lines = _reaction_evidence_lines(raw_reactions, [line.model_dump() for line in planned])
    merged = core.assemble_evidence(reaction_lines, [])

    # LLM 대기 중 같은 사용자의 동시 요청이 상한(#31)에 도달시켰을 수 있다 — INSERT 직전에 다시 읽어
    # 경합 구간을 수 ms로 줄인다(첫 검사는 모델을 부르기 전에 막는 빠른 실패용).
    current_max = service.max_attempt_no_for_requester(db, map_id=map_id, requested_by=requested_by)
    core.check_retry_limit(current_max)
    run = service.create_run(db, map_id=map_id, category=category, requested_by=requested_by, attempt_no=current_max + 1)
    service.add_reaction_evidence(db, run_id=run.id, lines=merged)

    circle, anchors = _default_circle_and_anchors(db, map_id=map_id, category=category)
    service.create_regions(
        db, run_id=run.id,
        regions_data=[_region_data(circle, label="기본 반경", confirmed=True, anchor_points=anchors)],
    )

    return run


def _evidence_response(line, principal: Principal) -> schemas.EvidenceLine:
    resource = Resource(type="evidence_line", map_id=principal.map_id, author_id=line.author_id)
    return schemas.EvidenceLine(
        id=str(line.id), author_id=line.author_id, text=line.text, badge=line.badge,
        fact_key=line.fact_key, fact_label=constraints.FACT_LABELS.get(line.fact_key) if line.fact_key else None,
        wants=line.wants, is_active=line.is_active,
        permissions=Permissions(can_disable=can(principal, "evidence.disable", resource)),
    )


def list_evidence(db: Session, *, run_id: str, principal: Principal) -> list[schemas.EvidenceLine]:
    service.get_run_or_404(db, run_id)
    return [_evidence_response(line, principal) for line in service.list_evidence(db, run_id)]


def patch_evidence(
    db: Session, *, run_id: str, principal: Principal,
    toggles: list[tuple[str, bool]], adds: list[str],
) -> list[schemas.EvidenceLine]:
    """PATCH /runs/{runId}/evidence (5-5). '-'는 author 본인만(evidence.disable, author-
    constrained) — 권한 없는 토글이 섞여 있으면 요청 전체를 403으로 거절한다(api-spec.yaml이
    이 엔드포인트에 Forbidden을 명시함 — "버튼이 애초에 disabled였어야 했다"는 신호)."""
    run = service.get_run_or_404(db, run_id)
    for evidence_id, is_active in toggles:
        line = service.get_evidence_or_none(db, evidence_id)
        if line is None or line.run_id != run.id:
            raise AppError("NOT_FOUND")
        resource = Resource(type="evidence_line", map_id=principal.map_id, author_id=line.author_id)
        if not can(principal, "evidence.disable", resource):
            raise AppError("FORBIDDEN")
        service.set_evidence_active(db, line.id, is_active)
    # 「+」로 추가한 줄도 ②를 거쳐 fact_key·wants를 붙인다(#254) — 안전 사유("조개 알러지")가 reference로만 남아
    # 실격이 안 켜지는 걸 막는다. 실패 시 동작은 create_run과 같다(PlanEvidenceFailed를 그대로 올린다).
    if adds:
        planned = llm_service.plan_evidence([
            {"author_id": principal.user_id, "source": "manual", "text": text, "badge": "reference", "fact_key": None}
            for text in adds
        ])
        for text, line in zip(adds, planned):
            service.add_manual_evidence(
                db, run_id=run.id, author_id=principal.user_id, text=text, fact_key=line.fact_key, wants=line.wants,
            )
    return [_evidence_response(line, principal) for line in service.list_evidence(db, run_id)]


def _region_response(region) -> schemas.Region:
    return schemas.Region(id=str(region.id), label=region.label, signature=region.signature, confirmed=region.confirmed)


def confirm_regions(db: Session, *, run_id: str, accept_union: bool) -> list[schemas.Region]:
    """POST /runs/{runId}/regions/confirm (5-6-1). v1은 항상 단일 기본값 원이라(아래
    _run_pipeline 참고) 실제로 REGION_CONFLICT가 나는 경로가 없다 — 겹침 판정 로직 자체는
    core.circles_all_overlap/region_signature 단위 테스트로 커버한다(recommend/for_Root.md)."""
    run = service.get_run_or_404(db, run_id)
    regions = service.list_regions(db, run_id)
    unconfirmed = [r for r in regions if not r.confirmed]
    if unconfirmed and not accept_union:
        raise AppError("REGION_CONFLICT", detail={"regions": [_region_response(r).model_dump() for r in regions]})
    service.confirm_all_regions(db, run.id)
    service.set_run_status(db, run, "executing")
    return [_region_response(r) for r in service.list_regions(db, run_id)]


def _active_hard_fact_keys(db: Session, run: RecommendRun) -> list[str]:
    """5-6 3단계 — "활성 실격 조건"(constraints.md)만 순회한다: is_active=True인 evidence_line 중 fact_key가
    매핑된 hard 키를 "안전 조건 사유는 배지와 무관하게 실격이다" 판정표대로 켠다(#254). required는 wants가
    true가 아니면(false·null) 켜고, preferred·reference는 wants=false일 때만 켠다. 켜진 키는 라벨이 참이든
    모름이든 제외한다(안전 조건, 가드레일 8). 카테고리에 안 맞는 fact_key는 애초에 제외."""
    lines = service.list_active_evidence(db, run.id)
    applicable = set(constraints.hard_fact_keys_for(run.category))
    active = {
        line.fact_key for line in lines
        if line.fact_key is not None
        and (line.wants is not True if line.badge == "required" else line.wants is False)
    }
    return sorted(active & applicable)


def _active_soft_requirements(db: Session, run: RecommendRun) -> list[tuple[str, bool]]:
    """#231 — soft 키 중 `required` + `wants`가 true/false인 활성 사유를 (fact_key, wants)로 켠다. wants가
    null이거나 hard 키(방향 고정)면 여기 오지 않는다. 사람이 직접 밝힌 사유라 카테고리 기본 키에 없어도
    적용한다(선호 사유와 같다 — 아래 soft_keys가 그 키의 체크를 붙인다)."""
    return sorted({
        (line.fact_key, line.wants) for line in service.list_active_evidence(db, run.id)
        if line.badge == "required" and line.wants is not None and line.fact_key in constraints.SOFT_FACT_KEYS
    })


def _passes_hard_check(fact_key: str, value) -> bool:
    if fact_key in constraints.VALUE_COMPARISON_UNSUPPORTED:
        # price_bucket — evidence_lines에 사용자 기준값을 담을 컬럼이 없어(스키마
        # 갭, recommend/for_Root.md) 실제 비교를 할 수 없다. known이어도 항상 통과시키고
        # Check로만 노출한다(정보 제공, 실격 판정 아님).
        return True
    return not bool(value)  # contains_shellfish/is_crowded_large — "있으면 실격"류


def _run_pipeline(
    db: Session, run: RecommendRun, *,
    place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway, excluded_place_ids: set[str],
) -> tuple[list[dict], list[dict]]:
    """5-6 실격 필터 순서(반경→영업종료→실격조건→중복제외→정렬)를 그대로 지킨다
    (recommend/CLAUDE.md "넘지 말 것" — 순서가 funnel 표의 의미를 결정한다)."""
    regions = service.list_regions(db, str(run.id))
    circles = [Circle(anchor_lat=r.center_lat, anchor_lng=r.center_lng, radius_m=r.radius_m) for r in regions]
    region_id = regions[0].id if regions else None

    pool = place_search.search_nearby(category=run.category, circles=circles)

    within_radius = [p for p in pool if core.is_within_any_region(p.lat, p.lng, circles)]
    removed_radius = len(pool) - len(within_radius)

    is_open_check = core.build_check("is_open", "pass", known=False, value=None, passes=True)
    removed_open = 0  # dev 스텁은 실시간 영업시간 조회가 없어 항상 unknown+needs_check — 결코 제거하지 않는다

    active_hard_keys = _active_hard_fact_keys(db, run)
    active_lines = service.list_active_evidence(db, run.id)
    soft_requirements = _active_soft_requirements(db, run)
    # 반대 사유(활성 required)를 낸 구성원 — fact_key로 구조화됐든 아니든 충족 집계에 센다(#255).
    disqualifier_authors = sorted({line.author_id for line in active_lines if line.badge == "required"})
    preferred_authors: dict[str, set[str]] = {}
    avoided_authors: dict[str, set[str]] = {}  # preferred + wants=false — 점수에서 반대 구성원(#231)
    for line in active_lines:
        # wants=None(방향을 모름)인 선호는 지지·반대 어디에도 세지 않는다 — 효과 없음(constraints.md 표, #237).
        if line.badge == "preferred" and line.fact_key is not None and line.wants is not None:
            by_direction = preferred_authors if line.wants else avoided_authors
            by_direction.setdefault(line.fact_key, set()).add(line.author_id)
    preferred_authors_frozen = {key: frozenset(authors) for key, authors in preferred_authors.items()}
    avoided_authors_frozen = {key: frozenset(authors) for key, authors in avoided_authors.items()}
    # 선호 라벨 체크는 이 카테고리에 적용되는 키 + 사람이 직접 원한 키만 붙인다 — 50여 개를 전부 붙이면
    # 「확인 필요」 체크가 넘치고, 원하지 않은 키는 어차피 점수에 쓰이지 않는다.
    soft_keys = sorted(
        set(constraints.soft_fact_keys_for(run.category))
        | (constraints.SOFT_FACT_KEYS & (preferred_authors.keys() | avoided_authors.keys()))
        | {fact_key for fact_key, _wants in soft_requirements}
    )
    # ③-a-1 — 라벨은 자체 DB(place_facts)에서 읽는다. 요청 중 모델을 부르지 않는다(#190, v1). 없는 라벨은
    # confidence=unknown으로 보고 unknown_policy를 그대로 적용한다. 한 번에 배치 조회(N+1 금지).
    facts_by_place = place_facts.get_facts([p.place_id for p in within_radius])
    checks_by_place: dict[str, list[Check]] = {}
    for place in within_radius:
        labels = facts_by_place.get(place.place_id, [])
        checks = [is_open_check]
        for fact_key in active_hard_keys:
            known, value = core.resolve_label(labels, fact_key)
            passes = _passes_hard_check(fact_key, value) if known else True
            checks.append(core.build_check(
                fact_key, constraints.HARD_REGISTRY[fact_key].unknown_policy, known=known, value=value, passes=passes,
                category=run.category,
            ))
        # #112 1단계 입력 — 선호(soft) 라벨도 같이 붙인다. unknown_policy는 표 그대로 "pass"
        # 고정(constraints.md — 순위에서 중립 처리). passed는 hard 체크처럼 "실격 아님"이 아니라
        # 그 라벨의 실제 참/거짓값이다.
        for fact_key in soft_keys:
            known, value = core.resolve_label(labels, fact_key)
            checks.append(core.build_check(fact_key, "pass", known=known, value=value, passes=bool(value)))
        checks_by_place[place.place_id] = checks

    pass_flags = core.apply_disqualifier_filters(
        [checks_by_place[p.place_id] for p in within_radius], soft_requirements,
    )
    after_disqualify = [p for p, ok in zip(within_radius, pass_flags) if ok]
    removed_disqualify = len(within_radius) - len(after_disqualify)

    after_exclusions = [p for p in after_disqualify if p.place_id not in excluded_place_ids]
    removed_exclusions = len(after_disqualify) - len(after_exclusions)

    # ③-b — #99 이후 모델이 아니라 코드가 점수를 매기고 상위 3곳을 고른다(recommend/core.py,
    # 이슈 #112). ♥ 받은 핀들의 라벨로 "선호 기준"을 만들고, 그 기준으로 통과 후보 각각에
    # 점수를 매긴 뒤, 점수 → 동네 배분 → 거리 평균 순으로 상위 3곳만 남긴다.
    liked_pins = pins_api.list_liked_pins(
        db, map_id=run.map_id, category=run.category, requested_by=run.requested_by,
    )
    # ♥ 핀의 라벨은 핀에 복사된 checks가 아니라 places의 place_facts에서 읽는다(#247) — 직접 찍은 핀도 같은
    # 라벨을 갖는다. known인 soft 라벨만 선호 신호가 된다(모름은 0점, 감점도 없다). 배치 조회 한 번.
    liked_facts = place_facts.get_facts([entry["place_id"] for entry in liked_pins]) if liked_pins else {}
    hearted_places = [
        core.HeartedPlace(
            checks=core.label_checks(liked_facts.get(entry["place_id"], [])),
            member_ids=frozenset(entry["member_ids"]),
        )
        for entry in liked_pins
    ]
    criteria = core.build_preference_criteria(
        hearted_places,
        excluded_fact_keys=constraints.VALUE_COMPARISON_UNSUPPORTED,
        disqualifying_fact_keys=[*active_hard_keys, *{fact_key for fact_key, _wants in soft_requirements}],
        preferred_authors=preferred_authors_frozen,
    )
    # #216 — 점수 계산은 전체 soft 체크를 쓰지만 저장·응답에는 사람이 원하지 않은 soft 체크(known 포함)를 싣지 않는다.
    # 사람이 원한 키 = 활성 근거 줄의 fact_key + ♥ 핀 기준으로 점수에 쓰인 키.
    wanted_soft_keys = {line.fact_key for line in active_lines if line.fact_key is not None} | {
        fact_key for fact_key, wanted in criteria.items() if wanted is True
    }
    # 방향이 있는 사유는 응답 체크를 "만족 여부"로 보인다(#237). 같은 키에 방향이 갈리면 required가 이긴다.
    directions: dict[str, bool] = {}
    for badge in ("preferred", "required"):
        directions.update({
            line.fact_key: line.wants for line in active_lines
            if line.badge == badge and line.fact_key in constraints.SOFT_FACT_KEYS and line.wants is not None
        })
    region_label = regions[0].label if regions else ""
    anchor_points_by_region = (
        {region_label: [tuple(point) for point in regions[0].anchor_points]} if regions else {}
    )
    scores = core.score_candidates(
        {p.place_id: checks_by_place[p.place_id] for p in after_exclusions}, hearted_places, criteria,
        preferred_authors_frozen, avoided_authors_frozen,
    )
    scored = [
        core.ScoredCandidate(place_id=p.place_id, score=scores[p.place_id], region_label=region_label, lat=p.lat, lng=p.lng)
        for p in after_exclusions
    ]
    top_place_ids = core.select_top_candidates(scored, anchor_points_by_region, limit=3) if scored else []
    places_by_id = {p.place_id: p for p in after_exclusions}
    removed_ranking = len(after_exclusions) - len(top_place_ids)

    candidates_data = []
    for index, place_id in enumerate(top_place_ids):
        place = places_by_id[place_id]
        checks = checks_by_place[place_id]
        fulfillment = core.build_member_fulfillment(
            checks, hearted_places, criteria, preferred_authors_frozen, disqualifier_authors,
        )
        # 이유 문장의 "(n/m명)"은 선호를 가진 구성원만 센다 — 실격 사유만 낸 사람을 선호 충족으로 부풀리지 않는다.
        preference_fulfillment = core.build_member_fulfillment(checks, hearted_places, criteria, preferred_authors_frozen)
        candidates_data.append({
            "place_id": place_id, "region_id": region_id, "lat": place.lat, "lng": place.lng,
            "rank": index + 1,
            "checks": [
                check.model_dump()
                for check in core.to_satisfaction_checks(core.checks_to_show(checks, wanted_soft_keys), directions)
            ],
            "member_fulfillment": fulfillment,
            "reason": core.build_reason(checks, criteria, preference_fulfillment),
            "place_source": dict(place.source) if place.source else None,
        })
    funnel = core.funnel_counts([
        ("카테고리 후보 풀", 0),
        ("반경 밖 제거", removed_radius),
        ("영업 종료 제거", removed_open),
        ("실격 조건 제거", removed_disqualify),
        ("이미 제안·거절됨", removed_exclusions),
        ("상위 3곳 선정", removed_ranking),
    ])
    return candidates_data, funnel


def _candidates_ready_event(
    db: Session, run: RecommendRun, candidates: list[CandidateRow], place_search: PlaceSearchGateway,
) -> Event:
    """docs/events.md run.candidates_ready — 스펙의 Candidate 모양 그대로(#241). 받는 사람은 요청자 본인
    하나라 permissions도 그 사람 기준으로 만든다(응답과 같은 _candidate_response)."""
    requester = Principal(user_id=run.requested_by, map_id=run.map_id, role="member")
    region_labels = {r.id: r.label for r in service.list_regions(db, str(run.id))}
    place_names = place_search.get_names([c.place_id for c in candidates]) if candidates else {}
    payload = {
        "run_id": str(run.id),
        "candidates": [
            _candidate_response(c, run, requester, region_labels, place_names).model_dump(exclude_none=True)
            for c in candidates
        ],
    }
    return Event(map_id=run.map_id, channel="private", type="run.candidates_ready",
                 payload=payload, recipient_user_id=run.requested_by)


def _excluded_place_ids(db: Session, run: RecommendRun) -> set[str]:
    """후보에서 뺄 place_id 전부(가드레일 6). 세 갈래를 합친다:
    1) exclusions의 `proposed`(다시 추천 받기로 이미 제안한 곳)·`dismissed`
    2) 요청자가 🚫한 핀의 장소 — 이 호출에서 `dismissed`로 exclusions에 쌓는다(#119). 핀이 지워진
       뒤에도 거절 이력이 남도록 pins가 삭제된 핀까지 돌려준다. add_exclusions는 이미 있는
       조합을 건너뛰므로 여러 번 불러도 안전하다(이미 proposed인 곳은 그대로 둔다).
    3) 이미 이 지도에 있는 핀(수동이든 게시된 것이든) — 안 빼면 게시하려는 순간 pins.unique(map_id,
       place_id)에 걸려 PIN_DUPLICATE(409)만 반복된다(루트 수정, 2026-09-23)."""
    service.add_exclusions(
        db, map_id=run.map_id, category=run.category,
        place_ids=pins_api.list_disliked_place_ids(
            db, user_id=run.requested_by, map_id=run.map_id, category=run.category,
        ),
        reason="dismissed", run_id=run.id, requested_by=run.requested_by,
    )
    return service.list_excluded_place_ids(
        db, map_id=run.map_id, requested_by=run.requested_by,
    ) | pins_api.list_place_ids_on_map(db, map_id=run.map_id)


def execute_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> RecommendRun:
    """POST /runs/{runId}/execute — 실격 필터(③-a-2) + 선호 순위(③-b) + 대안 반영(④)."""
    run = service.get_run_or_404(db, run_id)
    excluded = _excluded_place_ids(db, run)
    candidates_data, funnel = _run_pipeline(
        db, run, place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded,
    )
    candidates = service.replace_unpublished_candidates(db, run_id=run.id, candidates_data=candidates_data)
    service.set_last_funnel(db, run, funnel)
    service.set_run_status(db, run, "done")
    record_event(db, _candidates_ready_event(db, run, candidates, place_search))
    return run


def widen_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> RecommendRun:
    """POST /runs/{runId}/widen (5-6-1, 가드레일4) — 기본값 원을 +5분(도보) 넓힌다. 상한(30분)에
    이미 닿았으면 409 WIDEN_LIMIT(core.next_default_radius_walk_min). v1은 사람이 명시한 원과
    기본값 원을 구분할 방법이 없어 — 반경 사유가 구조화되기 전이라 명시적 원이 저장되지 않는다 —
    저장된 원 전부가 기본값 원이다. 명시적 원이 생기면 그 원은 여기서 건드리지 않도록 좁혀야
    한다(recommend/for_Root.md)."""
    run = service.get_run_or_404(db, run_id)
    regions = service.list_regions(db, run_id)
    if not regions:
        raise AppError("NOT_READY")
    next_walk_min = core.next_default_radius_walk_min(run.default_radius_walk_min)  # 409 WIDEN_LIMIT
    radius_m = core.radius_m_for_walk_min(next_walk_min)
    for region in regions:
        widened = Circle(anchor_lat=region.center_lat, anchor_lng=region.center_lng, radius_m=radius_m)
        service.update_region_radius(db, region, radius_m=radius_m, signature=core.region_signature([widened]))
    service.set_default_radius_walk_min(db, run, next_walk_min)

    service.set_run_status(db, run, "executing")
    excluded = _excluded_place_ids(db, run)
    candidates_data, funnel = _run_pipeline(
        db, run, place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded,
    )
    candidates = service.replace_unpublished_candidates(db, run_id=run.id, candidates_data=candidates_data)
    service.set_last_funnel(db, run, funnel)
    service.set_run_status(db, run, "done")
    record_event(db, _candidates_ready_event(db, run, candidates, place_search))
    return run


def retry_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> RecommendRun:
    """POST /runs/{runId}/retry (3절) — 현재 뜬(아직 게시 안 된) 대안 전체를 제외목록에
    넣고 새로 찾는다. 상한 도달 시 429 RETRY_LIMIT(#31)."""
    run = service.get_run_or_404(db, run_id)
    # run.attempt_no(이 run 자신의 값)가 아니라 그 사람의 전체 run 중 최댓값을 본다 — #31은
    # 개인 단위 공유 카운터라, 오래된(attempt_no가 낮은) run으로 retry를 걸면 그 run 자신의
    # 값만 통과해서 사실상 상한을 우회할 수 있었다(루트 수정, 2026-09-23 — Antigravity 검수로
    # 발견). bump_attempt_no도 같은 기준으로 다시 계산해 맞춘다.
    current_max = service.max_attempt_no_for_requester(db, map_id=run.map_id, requested_by=run.requested_by)
    core.check_retry_limit(current_max)

    current_candidates = service.list_candidates(db, run_id)
    unpublished_place_ids = [c.place_id for c in current_candidates if c.published_pin_id is None]
    service.add_exclusions(
        db, map_id=run.map_id, category=run.category, place_ids=unpublished_place_ids,
        reason="proposed", run_id=run.id, requested_by=run.requested_by,
    )
    service.bump_attempt_no(db, run)

    excluded = _excluded_place_ids(db, run)
    candidates_data, funnel = _run_pipeline(
        db, run, place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded,
    )
    candidates = service.replace_unpublished_candidates(db, run_id=run.id, candidates_data=candidates_data)
    service.set_last_funnel(db, run, funnel)
    service.set_run_status(db, run, "done")
    record_event(db, _candidates_ready_event(db, run, candidates, place_search))
    return run


def _candidate_response(
    candidate: CandidateRow, run: RecommendRun, principal: Principal, region_labels: dict, place_names: Mapping[str, str],
) -> schemas.Candidate:
    resource = Resource(type="candidate", map_id=run.map_id, author_id=run.requested_by)
    # can()은 역할·작성자만 본다(published_pin_id 같은 candidate 상태를 모른다) — 이미 게시된
    # candidate에도 can_publish=true가 나가면 FE가 게시 버튼을 계속 활성 상태로 그린다(루트가
    # docs/data-model.md에 미리 남겨둔 주의사항, #57/#64 처리 중 발견 — #108 구현이 놓쳐서
    # 여기서 직접 고친다). 게시 여부는 이 함수가 이미 알고 있으니 여기서 같이 확인한다.
    already_published = candidate.published_pin_id is not None
    return schemas.Candidate(
        id=str(candidate.id), place_name=place_names.get(candidate.place_id), region_label=region_labels.get(candidate.region_id),
        lat=candidate.lat, lng=candidate.lng,
        rank=candidate.rank, checks=[Check(**c) for c in candidate.checks],
        reason=candidate.reason,
        member_fulfillment=candidate.member_fulfillment or None,  # {} = 집계 없음 → 필드 생략
        place_source=candidate.place_source,
        visibility="published" if already_published else "private",
        published_pin_id=str(candidate.published_pin_id) if already_published else None,
        permissions=Permissions(
            can_publish=(not already_published) and can(principal, "recommend.publish", resource)
        ),
    )


def get_result(
    db: Session, *, run_id: str, principal: Principal, place_search: PlaceSearchGateway,
) -> schemas.RecommendResult:
    """GET /runs/{runId}/result — funnel은 마지막 execute/widen/retry가 저장해둔 값을 그대로
    쓴다(재계산하지 않는다 — GET은 부작용도, 외부 게이트웨이 의존도 없어야 한다)."""
    run = service.get_run_or_404(db, run_id)
    regions = service.list_regions(db, run_id)
    region_labels = {r.id: r.label for r in regions}
    candidates = service.list_candidates(db, run_id)
    funnel = run.last_funnel or []
    # 후보 이름은 places(자체 DB)에서 온다 — candidates에는 place_id·좌표만 저장한다(#190).
    place_names = place_search.get_names([c.place_id for c in candidates]) if candidates else {}
    if not candidates:
        raise AppError("NO_RESULTS", detail={"funnel": funnel})
    return schemas.RecommendResult(
        run_id=str(run.id),
        funnel=[schemas.FunnelEntry(**entry) for entry in funnel],
        regions=[_region_response(r) for r in regions],
        candidates=[_candidate_response(c, run, principal, region_labels, place_names) for c in candidates],
    )
