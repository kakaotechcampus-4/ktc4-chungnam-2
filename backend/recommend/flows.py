"""
recommend의 기능 실행 함수 전체 — 다른 모듈 접근(pins.api/maps.api/llm.service/authz/
recommend.ports 게이트웨이)은 전부 이 파일에 둔다(이 모듈 자체 관례 — service.py는 recommend
소유 테이블만, core.py는 순수 판정만). 커밋하지 않는다(common/database.py get_db가 요청당
한 번 커밋한다).

**publish_candidate** — 「지도에 올리기」, mentor-review-plan.md 결정(#71 PR).
**아래 나머지 함수 전부** — #108(코어 파이프라인, llm 스텁 대상 통합) 범위. v1은 실제 비동기
큐가 없어 "202 진행 중"을 문자 그대로 구현하지 않는다 — run 생성·execute·widen·retry 전부
동기로 끝낸다(recommend/for_Root.md에 기록). places(#14)/seeding(#13)이 없어 candidate 풀
확보(PlaceSearchGateway)·장소 원자료 조회(PlaceFactsGateway) 둘 다 recommend/deps.py의 dev
스텁이 채운다 — 실제 장소 데이터가 아니다.

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
from typing import Any

from sqlalchemy.orm import Session

from auth.schemas import CurrentUser
from authz.core import Principal, Resource, can
from authz.guard import require
from authz.ports import MembershipGateway
from authz.schemas import Permissions
from common.errors import AppError
from common.events import Event, record_event
from common.geo import WALKING_SPEED_M_PER_MIN
from llm import service as llm_service
from maps import api as maps_api
from pins import api as pins_api
from pins.models import Pin as PinRow
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


def publish_candidate(
    db: Session, *, candidate_id: str, requester_id: str, membership: MembershipGateway,
) -> PinRow:
    candidate, run = service.load_candidate_with_run(db, candidate_id)  # 1) 404 NOT_FOUND

    _require_publish(
        loaded=_LoadedCandidate(
            resource=Resource(type="candidate", map_id=run.map_id, author_id=run.requested_by),
            obj=candidate,
        ),
        user=CurrentUser(user_id=requester_id),
        gateway=membership,
    )  # 2)+3) 비구성원 404 NOT_FOUND / 구성원인데 본인 요청 아님 403 FORBIDDEN
    # ↑ 여기까지 통과해야만 아래로 내려간다 — 순서를 바꾸지 않는다(멤버십/작성자 확인이
    #   멱등 경로·NOT_READY 판정보다 항상 먼저).

    if candidate.published_pin_id is not None:  #    멱등 빠른 경로 — run 상태와 무관하게 항상 통한다
        return pins_api.get_pin_for_viewer(
            db, pin_id=str(candidate.published_pin_id), viewer_id=requester_id
        )  #    200, 이벤트 없음
        # get_pin_for_viewer가 NOT_FOUND/AI_PIN_PRIVATE를 던지면(핀이 그 사이 삭제됐거나
        # 비공개로 바뀐 극단적 경우) 그대로 전파한다 — 별도 처리 없음, 정직한 실패가 낫다.

    core.check_run_ready(run)  # 4) 409 NOT_READY

    mutation = pins_api.create_ai_pin(
        db, map_id=run.map_id, category=run.category, place_id=candidate.place_id,
        lat=candidate.lat, lng=candidate.lng, created_by=requester_id,
    )  # 5) INSERT pins (레이스 1번 — uq_pins_map_place 위반 시 여기서 PIN_DUPLICATE)
    service.link_published_pin(db, candidate_id=candidate_id, pin_id=str(mutation.pin.id))  # 6) 가드 UPDATE

    # pins.api.create_ai_pin이 이제 pin.published 타입으로 직접 이벤트를 만든다(루트가
    # pins/core.py에 pin_published_event를 추가해 근본 수정 — 예전엔 여기서 type만 교정하는
    # 우회가 있었다).
    record_event(db, mutation.event)  # 7) event_log — mutation과 같은 db 세션, 커밋 전
    return mutation.pin  # 8) get_db가 커밋


# ============================================================================
# #108 — 코어 파이프라인(llm 스텁 대상 통합)
# ============================================================================

CATEGORIES: list[str] = ["음식점", "카페", "숙소", "관광지"]
# 기본값 원 반경(m) — 최종기획안.md 248행에 이미 정의돼 있다: "기본 반경(도보 15분에 해당하는
# 거리)". common.geo.WALKING_SPEED_M_PER_MIN(도보 시간 근사 보정계수)으로 환산한다 — 루트
# 검증 중 발견: 이전 버전은 이 스펙을 못 찾고 2000m(약 25분)를 임의로 썼었다. 계산식으로
# 두면 나중에 WALKING_SPEED_M_PER_MIN이 바뀌어도 같이 맞다.
DEFAULT_REGION_RADIUS_M = 15 * WALKING_SPEED_M_PER_MIN  # 15분 * 80m/분 = 1200m


def get_readiness(db: Session, *, map_id: str) -> dict[str, dict]:
    """GET /maps/{mapId}/recommend/readiness (5-4). N(#32)의 정의가 결정 이슈 미결이라
    "이 지도의 전체 구성원 수"로 잠정 구현했다(maps.api.count_members, for_Root.md 보고)."""
    member_count = maps_api.count_members(db, map_id)
    return {
        category: core.check_readiness(
            pins_api.count_reacted_users(db, map_id=map_id, category=category), member_count
        )
        for category in CATEGORIES
    }


def _evidence_from_reaction(reaction: dict) -> dict:
    """반응 하나를 llm.schemas.EvidenceLine 생성 가능한 dict로 — 실제 ②(사유 구조화, 모델
    확정 #12 전) 없이는 자유 텍스트에서 fact_key를 안전하게 추론할 수 없어 fact_key는 항상
    None으로 둔다(값을 지어내지 않는다는 llm/CLAUDE.md 원칙과 같은 이유 — 실격 조건은 확실할
    때만 활성화되어야 한다). badge만 반응 종류로 잠정 매핑한다: 🚫(against)는 반드시 사유가
    있고(가드레일3) 실격 성격이 강해 required, ♥/△는 preferred로 낮춘다."""
    return {
        "author_id": reaction["user_id"],
        "source": "reaction",
        "text": reaction["reason_text"],
        "badge": "required" if reaction["type"] == "against" else "preferred",
        "fact_key": None,
    }


def _default_circle(db: Session, *, map_id: str, category: str) -> Circle:
    """지역(regions) 기본값 — places가 없어 실제 검색 범위를 스스로 정할 방법이 이것뿐이다:
    그 카테고리 핀들의 중심 좌표 + 고정 반경. 실제 반경 사유(circle_anchor_pin_id 등)가
    구조화되는 순간(모델 확정 이후) 이 기본값은 "사람이 명시하지 않았을 때만" 쓰여야 한다
    (recommend/for_Root.md에 상세 기록)."""
    coordinates = pins_api.get_category_pin_coordinates(db, map_id=map_id, category=category)
    if not coordinates:
        raise AppError("NOT_READY")
    center_lat = sum(lat for _, lat, _ in coordinates) / len(coordinates)
    center_lng = sum(lng for _, _, lng in coordinates) / len(coordinates)
    return Circle(anchor_lat=center_lat, anchor_lng=center_lng, radius_m=DEFAULT_REGION_RADIUS_M)


def _region_data(circle: Circle, *, label: str, confirmed: bool) -> dict:
    return {
        "signature": core.region_signature([circle]),
        "label": label,
        "center_lat": circle.anchor_lat,
        "center_lng": circle.anchor_lng,
        "radius_m": circle.radius_m,
        "confirmed": confirmed,
        "confirmed_at": datetime.now(timezone.utc) if confirmed else None,
    }


def create_run(db: Session, *, map_id: str, category: str, requested_by: str) -> RecommendRun:
    """POST /maps/{mapId}/runs — run 생성 + 근거 조립(①②) + 기본값 지역 계산까지 한 요청
    안에서 동기로 끝낸다. 순서: 1) 준비 판정(409 NOT_READY) 2) 재시도 상한(#31) 3) run INSERT
    4) 반응 → 근거 구조화(llm.plan_evidence) → evidence_lines INSERT 5) 기본값 지역 INSERT."""
    readiness = core.check_readiness(
        pins_api.count_reacted_users(db, map_id=map_id, category=category),
        maps_api.count_members(db, map_id),
    )
    if not readiness["ready"]:
        raise AppError("NOT_READY", detail=readiness)

    current_max = service.max_attempt_no_for_requester(db, map_id=map_id, requested_by=requested_by)
    core.check_retry_limit(current_max)  # #31 — 카테고리 무관 개인 단위 카운터가 이미 상한이면 새 run도 막는다
    run = service.create_run(db, map_id=map_id, category=category, requested_by=requested_by, attempt_no=current_max + 1)

    raw_reactions = pins_api.list_reasoned_reactions(db, map_id=map_id, category=category)
    reaction_lines = [_evidence_from_reaction(r) for r in raw_reactions]
    planned = llm_service.plan_evidence(reaction_lines)  # ② — v1 스텁은 스키마 검증만 하고 그대로 통과시킨다
    merged = core.assemble_evidence([line.model_dump() for line in planned], [])
    service.add_reaction_evidence(db, run_id=run.id, lines=merged)

    circle = _default_circle(db, map_id=map_id, category=category)
    service.create_regions(db, run_id=run.id, regions_data=[_region_data(circle, label="기본 반경", confirmed=True)])

    return run


def _evidence_response(line, principal: Principal) -> schemas.EvidenceLine:
    resource = Resource(type="evidence_line", map_id=principal.map_id, author_id=line.author_id)
    return schemas.EvidenceLine(
        id=str(line.id), author_id=line.author_id, text=line.text, badge=line.badge,
        fact_key=line.fact_key, is_active=line.is_active,
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
    for text in adds:
        service.add_manual_evidence(db, run_id=run.id, author_id=principal.user_id, text=text)
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
    """5-6 3단계 — "활성 실격 조건"(constraints.md)만 순회한다: is_active=True인
    evidence_line 중 badge='required'로 fact_key가 매핑된 것만 실격 대상으로 켠다(누구도
    문제 제기 안 한 조건은 검사하지 않는다). 카테고리에 안 맞는 fact_key는 애초에 제외."""
    lines = service.list_active_evidence(db, run.id)
    applicable = set(constraints.hard_fact_keys_for(run.category))
    active = {line.fact_key for line in lines if line.badge == "required" and line.fact_key is not None}
    return sorted(active & applicable)


def _passes_hard_check(fact_key: str, value) -> bool:
    if fact_key in constraints.VALUE_COMPARISON_UNSUPPORTED:
        # price_bucket/capacity_min — evidence_lines에 사용자 기준값을 담을 컬럼이 없어(스키마
        # 갭, recommend/for_Root.md) 실제 비교를 할 수 없다. known이어도 항상 통과시키고
        # Check로만 노출한다(정보 제공, 실격 판정 아님).
        return True
    return not bool(value)  # contains_shellfish/spicy_focused/oily_focused/is_crowded_large — "있으면 실격"류


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
    checks_by_place: dict[str, list[Check]] = {}
    for place in within_radius:
        raw_facts = place_facts.get_raw_facts(place.place_id)
        labels = llm_service.label_place(raw_facts, active_hard_keys)  # ③-a-1
        checks = [is_open_check]
        for label in labels:
            spec = constraints.HARD_REGISTRY[label.fact_key]
            known = label.confidence == "known"
            passes = _passes_hard_check(label.fact_key, label.value) if known else True
            checks.append(core.build_check(label.fact_key, spec.unknown_policy, known=known, value=label.value, passes=passes))
        checks_by_place[place.place_id] = checks

    pass_flags = core.apply_disqualifier_filters([checks_by_place[p.place_id] for p in within_radius])
    after_disqualify = [p for p, ok in zip(within_radius, pass_flags) if ok]
    removed_disqualify = len(within_radius) - len(after_disqualify)

    after_exclusions = [p for p in after_disqualify if p.place_id not in excluded_place_ids]
    removed_exclusions = len(after_disqualify) - len(after_exclusions)

    ranked = llm_service.rank_candidates([p.place_id for p in after_exclusions])  # ③-b
    rank_by_place = {r.place_id: r.rank for r in ranked}

    candidates_data = [
        {
            "place_id": p.place_id, "region_id": region_id, "lat": p.lat, "lng": p.lng,
            "rank": rank_by_place.get(p.place_id, index + 1),
            "checks": [check.model_dump() for check in checks_by_place[p.place_id]],
            "member_fulfillment": {},  # 구성원별 선호 충족 집계 — evidence_lines에 구성원별
            # 선호값을 담을 구조가 없어(위 _passes_hard_check와 같은 종류의 스키마 갭) v1은
            # 항상 빈 dict다(recommend/for_Root.md에 보고).
        }
        for index, p in enumerate(after_exclusions)
    ]
    funnel = core.funnel_counts([
        ("카테고리 후보 풀", 0),
        ("반경 밖 제거", removed_radius),
        ("영업 종료 제거", removed_open),
        ("실격 조건 제거", removed_disqualify),
        ("이미 제안·거절됨", removed_exclusions),
    ])
    return candidates_data, funnel


def _candidates_ready_event(run: RecommendRun, candidates: list[CandidateRow]) -> Event:
    payload = {
        "run_id": str(run.id),
        "candidates": [
            {"id": str(c.id), "rank": c.rank, "checks": c.checks, "visibility": "private"}
            for c in candidates
        ],
    }
    return Event(map_id=run.map_id, channel="private", type="run.candidates_ready",
                 payload=payload, recipient_user_id=run.requested_by)


def execute_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> RecommendRun:
    """POST /runs/{runId}/execute — 실격 필터(③-a-2) + 선호 순위(③-b) + 대안 반영(④)."""
    run = service.get_run_or_404(db, run_id)
    # 제안·거절 이력(exclusions) + 이미 이 지도에 있는 핀(수동이든 게시된 것이든) 둘 다
    # 뺀다 — 후자를 빼먹으면 이미 핀으로 있는 장소가 그대로 다시 추천되고, 게시하려는 순간
    # pins.unique(map_id, place_id) 제약에 걸려 PIN_DUPLICATE(409)만 반복된다(루트 수정,
    # 2026-09-23 — Antigravity 검수로 발견).
    excluded = service.list_excluded_place_ids(
        db, map_id=run.map_id, requested_by=run.requested_by,
    ) | pins_api.list_place_ids_on_map(db, map_id=run.map_id)
    candidates_data, funnel = _run_pipeline(
        db, run, place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded,
    )
    candidates = service.replace_unpublished_candidates(db, run_id=run.id, candidates_data=candidates_data)
    service.set_last_funnel(db, run, funnel)
    service.set_run_status(db, run, "done")
    record_event(db, _candidates_ready_event(run, candidates))
    return run


def widen_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> None:
    """POST /runs/{runId}/widen (5-6-1, 가드레일4) — 기본값 원만 확대한다. v1은 사람이 명시한
    원과 기본값 원을 구분할 방법이 없어(위 _default_circle 참고) 저장된 원 전부를 넓힌다 —
    실제 반경 사유가 구조화되면 이 함수는 "명시적 원은 건드리지 않는다"로 좁혀져야 한다
    (recommend/for_Root.md, 루트 확인 필요)."""
    run = service.get_run_or_404(db, run_id)
    regions = service.list_regions(db, run_id)
    if not regions:
        raise AppError("NOT_READY")
    for region in regions:
        widened = core.widen_radius(Circle(anchor_lat=region.center_lat, anchor_lng=region.center_lng, radius_m=region.radius_m))
        signature = core.region_signature([widened])
        service.update_region_radius(db, region, radius_m=widened.radius_m, signature=signature)

    service.set_run_status(db, run, "executing")
    # 제안·거절 이력(exclusions) + 이미 이 지도에 있는 핀(수동이든 게시된 것이든) 둘 다
    # 뺀다 — 후자를 빼먹으면 이미 핀으로 있는 장소가 그대로 다시 추천되고, 게시하려는 순간
    # pins.unique(map_id, place_id) 제약에 걸려 PIN_DUPLICATE(409)만 반복된다(루트 수정,
    # 2026-09-23 — Antigravity 검수로 발견).
    excluded = service.list_excluded_place_ids(
        db, map_id=run.map_id, requested_by=run.requested_by,
    ) | pins_api.list_place_ids_on_map(db, map_id=run.map_id)
    candidates_data, funnel = _run_pipeline(
        db, run, place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded,
    )
    candidates = service.replace_unpublished_candidates(db, run_id=run.id, candidates_data=candidates_data)
    service.set_last_funnel(db, run, funnel)
    service.set_run_status(db, run, "done")
    record_event(db, _candidates_ready_event(run, candidates))


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

    # 제안·거절 이력(exclusions) + 이미 이 지도에 있는 핀(수동이든 게시된 것이든) 둘 다
    # 뺀다 — 후자를 빼먹으면 이미 핀으로 있는 장소가 그대로 다시 추천되고, 게시하려는 순간
    # pins.unique(map_id, place_id) 제약에 걸려 PIN_DUPLICATE(409)만 반복된다(루트 수정,
    # 2026-09-23 — Antigravity 검수로 발견).
    excluded = service.list_excluded_place_ids(
        db, map_id=run.map_id, requested_by=run.requested_by,
    ) | pins_api.list_place_ids_on_map(db, map_id=run.map_id)
    candidates_data, funnel = _run_pipeline(
        db, run, place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded,
    )
    candidates = service.replace_unpublished_candidates(db, run_id=run.id, candidates_data=candidates_data)
    service.set_last_funnel(db, run, funnel)
    service.set_run_status(db, run, "done")
    record_event(db, _candidates_ready_event(run, candidates))
    return run


def _candidate_response(candidate: CandidateRow, run: RecommendRun, principal: Principal, region_labels: dict) -> schemas.Candidate:
    resource = Resource(type="candidate", map_id=run.map_id, author_id=run.requested_by)
    # can()은 역할·작성자만 본다(published_pin_id 같은 candidate 상태를 모른다) — 이미 게시된
    # candidate에도 can_publish=true가 나가면 FE가 게시 버튼을 계속 활성 상태로 그린다(루트가
    # docs/data-model.md에 미리 남겨둔 주의사항, #57/#64 처리 중 발견 — #108 구현이 놓쳐서
    # 여기서 직접 고친다). 게시 여부는 이 함수가 이미 알고 있으니 여기서 같이 확인한다.
    already_published = candidate.published_pin_id is not None
    return schemas.Candidate(
        id=str(candidate.id), region_label=region_labels.get(candidate.region_id),
        rank=candidate.rank, checks=[Check(**c) for c in candidate.checks],
        visibility="published" if already_published else "private",
        published_pin_id=str(candidate.published_pin_id) if already_published else None,
        permissions=Permissions(
            can_publish=(not already_published) and can(principal, "recommend.publish", resource)
        ),
    )


def get_result(db: Session, *, run_id: str, principal: Principal) -> schemas.RecommendResult:
    """GET /runs/{runId}/result — funnel은 마지막 execute/widen/retry가 저장해둔 값을 그대로
    쓴다(재계산하지 않는다 — GET은 부작용도, 외부 게이트웨이 의존도 없어야 한다)."""
    run = service.get_run_or_404(db, run_id)
    regions = service.list_regions(db, run_id)
    region_labels = {r.id: r.label for r in regions}
    candidates = service.list_candidates(db, run_id)
    funnel = run.last_funnel or []
    if not candidates:
        raise AppError("NO_RESULTS", detail={"funnel": funnel})
    return schemas.RecommendResult(
        run_id=str(run.id),
        funnel=[schemas.FunnelEntry(**entry) for entry in funnel],
        regions=[_region_response(r) for r in regions],
        candidates=[_candidate_response(c, run, principal, region_labels) for c in candidates],
    )
