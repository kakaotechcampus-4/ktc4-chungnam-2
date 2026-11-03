"""
recommend의 기능 실행 함수 전체 — 다른 모듈 접근(pins.api/maps.api/llm.api(Gateway)/authz/
recommend.ports 게이트웨이)은 전부 이 파일에 둔다(이 모듈 자체 관례 — service.py는 recommend
소유 테이블만, core.py는 순수 판정만). 커밋하지 않는다(common/database.py get_db가 요청당
한 번 커밋한다).

**publish_candidate** — 「지도에 올리기」, mentor-review-plan.md 결정(#71 PR).
**아래 나머지 함수 전부** — #108(코어 파이프라인, llm 스텁 대상 통합) 범위. v1은 실제 비동기
큐가 없어 "202 진행 중"을 문자 그대로 구현하지 않는다 — run 생성·execute·widen·retry 전부
동기로 끝낸다(docs/events.md "v1에서 발행하지 않는 이벤트"). places(#14)/seeding(#13)이 없어 candidate 풀
확보(PlaceSearchGateway)·라벨 조회(PlaceFactsGateway)는 dev 모드면 recommend/deps.py의 스텁이,
real 모드면 places.api의 자체 DB 함수가 채운다(#190 — 모델 호출은 ② 사유 구조화 하나뿐이다).

**mentor-review-plan.md 대비 실제 구현 차이 (PR #71)**:
계획 문서(작성 09-11 22:46)는 `membership: MembershipGateway`에 `.is_member(map_id, user_id)
-> bool`이 있다고 전제했다 — 이건 `pins/ports.py`가 갖고 있던 옛 Protocol인데, pins의 PR #71
재작업(09-12 00:10~00:24, 계획보다 늦게 끝남)에서 이미 삭제됐다. 그 사이 `docs/permissions.md`
("권한을 어디서 강제하는가" 절, 계약 변경)가 이미 확정한 실제 규칙은 다음과 같다:
  - 비구성원(role=None) → **404 NOT_FOUND** (계획의 403 FORBIDDEN이 아니다 — 존재를 안 흘린다)
  - 구성원이지만 그 액션이 롤에 없음 → **403 FORBIDDEN** (docs/permissions.md는 404/403 두
    값만 규정한다 — 계획의 "AI_PIN_PRIVATE"는 이 문서보다 먼저 쓰인 추측이었다. `recommend.
    publish`는 `candidate.requested_by`(=run.requested_by) 본인만 가능하도록
    authz/policy.py의 author.actions에만 있어 본인이 아니면 403이 된다)
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

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Collection, Mapping, Sequence

from sqlalchemy.orm import Session

from auth.schemas import CurrentUser
from authz.core import Principal, Resource, can
from authz.guard import require
from authz.ports import MembershipGateway
from authz.schemas import Permissions
from common import categories, geo
from common.errors import AppError
from common.events import Event, record_event
from credits import api as credits_api
from llm import api as llm_api
from maps import api as maps_api
from pins import api as pins_api
from pins.schemas import Pin
from places import api as places_api
from places.schemas import PlaceInfo
from recommend import constraints, core, schemas, service
from recommend.models import Candidate as CandidateRow
from recommend.models import EvidenceLine as EvidenceLineRow
from recommend.models import RecommendRun
from recommend.ports import Circle, EvidencePlanGateway, PlaceFactsGateway, PlaceSearchGateway, PlaceStub
from recommend.schemas import Check


@dataclass(frozen=True)
class _LoadedCandidate:
    """authz.guard.require()가 기대하는 `Loaded` 모양(.resource/.obj)을 흉내낸다 — FastAPI
    라우트가 아니라 이 함수가 직접 부르므로 loader Depends 없이 이미 읽은 candidate로 채운다."""

    resource: Resource
    obj: Any


DEFAULT_REGION_LABEL = "기본 반경"   # 기본 지역의 이름 — run 생성과 미리 돌려 보기(#1180)가 같이 쓴다

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
        #    200, 이벤트 없음. get_pin_response_for_viewer가 NOT_FOUND를 던지면(핀이 그
        #    사이 삭제된 극단적 경우) 그대로 전파한다 — 정직한 실패가 낫다.

    # 같은 run의 실행·재시도·넓히기·후보 교체와 겹치지 않게 run을 잠그고, 기다린 사이 바뀐 후보를 다시 읽는다(#811).
    # 후보가 그 사이 교체돼 사라졌으면 여기서 404다. 잠금은 커밋까지 가서 게시 INSERT와 후보 링크가 한 덩어리로 보인다.
    service.lock_run(db, run.id)
    candidate, run = service.load_candidate_with_run(db, candidate_id)
    if candidate.published_pin_id is not None:
        return _published_pin_response(db, pin_id=str(candidate.published_pin_id), requester_id=requester_id, run=run)

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


def list_runs(
    db: Session, *, map_id: str, requested_by: str, category: str | None, limit: int,
) -> list[schemas.RunSummary]:
    """GET /maps/{mapId}/runs (#469) — 내가 요청한 run만, 최근순. 남의 run은 어떤 경로로도 섞이지 않는다."""
    return [
        schemas.RunSummary(
            id=str(run.id), map_id=run.map_id, category=run.category, status=run.status, attempt_no=run.attempt_no,
            created_at=run.created_at, candidate_count=candidate_count, published_count=published_count,
        )
        for run, candidate_count, published_count in service.list_runs_for_requester(
            db, map_id=map_id, requested_by=requested_by, category=category, limit=limit,
        )
    ]


def get_readiness(db: Session, *, map_id: str, place_search: PlaceSearchGateway) -> dict[str, dict]:
    """GET /maps/{mapId}/recommend/readiness (5-4). 카테고리마다 ♥/🚫 의견이 달린 핀이 1곳 이상이면 열린다
    (#360 — 구성원 수와 무관, 혼자 쓰는 지도도 같다). 준비 판정에 정예 장소 수(curated_nearby, #798)를 덧붙인다."""
    result = {}
    for category in CATEGORIES:
        readiness = readiness_for_category(db, map_id=map_id, category=category)
        result[category] = {**readiness, **_curated_nearby(db, map_id=map_id, category=category,
                                                             readiness=readiness, place_search=place_search)}
    return result


def _curated_nearby(
    db: Session, *, map_id: str, category: str, readiness: dict, place_search: PlaceSearchGateway,
) -> dict:
    """기본 지역(create_run과 같은 원)에서 반경 넓히기 상한 안의 정예 장소 수(#798). 풀 반경과 같은 배율이라
    (core.pool_radius_factor, #792) 실행이 끝까지 넓혀도 볼 수 있는 장소 수다. 0이면 카카오맵 검색 링크를 함께 준다.
    의견 핀이 없거나 좌표 있는 핀이 없어 기본 지역이 없으면 둘 다 없다."""
    default_region = _default_circle_and_anchors(db, map_id=map_id, category=category) if readiness["answered_count"] else None
    if default_region is None:
        return {}
    circle, anchors = default_region
    pool_radius_m = round(circle.radius_m * core.pool_radius_factor(core.radius_walk_mins(category)[0], category))
    count = place_search.count_curated(
        category=category, circles=[Circle(anchor_lat=lat, anchor_lng=lng, radius_m=pool_radius_m) for lat, lng in anchors],
    )
    if count:
        return {"curated_nearby": count}
    external = _external_search(db, map_id=map_id, category=category, place_search=place_search)
    return {"curated_nearby": 0, "external_search": external.model_dump()}


def _search_area(db: Session, *, map_id: str, category: str, place_search: PlaceSearchGateway) -> str | None:
    """카카오맵 검색어의 동네(#800 결정). ① 이 지도에서 그 카테고리 핀들의 장소 주소에 가장 많은 동네 — 기본 지역이 그
    핀들의 중심이라 실제 후보가 있는 곳이다 ② 없으면(실시간 핀만 있는 등) 지도의 지역 이름 ③ 그것도 없으면 None(말만)."""
    places = place_search.get_places(sorted(pins_api.list_place_ids_on_map(db, map_id=map_id)))
    area = core.most_common_area(
        places_api.neighborhood(info.address) for info in places.values() if info.category == category
    )
    return area or maps_api.get_map_region_label(db, map_id)


def _external_search(
    db: Session, *, map_id: str, category: str, place_search: PlaceSearchGateway,
) -> schemas.ExternalSearch:
    """카카오맵 검색 링크(docs/constraints.md 「카카오맵 검색 링크」) — 검색어는 `{동네} {카테고리 말}` 하나다(#904)."""
    area = _search_area(db, map_id=map_id, category=category, place_search=place_search)
    query = core.external_search_query(area, category)
    return schemas.ExternalSearch(query=query, url=places_api.kakao_search_url(query))


def _run_external_search(db: Session, run: RecommendRun, place_search: PlaceSearchGateway) -> schemas.ExternalSearch:
    return _external_search(db, map_id=run.map_id, category=run.category, place_search=place_search)


def readiness_for_category(db: Session, *, map_id: str, category: str) -> dict:
    """카테고리 하나의 준비 판정(⓪) — 라우터(get_readiness), create_run, recommend.api.get_readiness(#530)가
    모두 이 함수를 쓴다. 계산을 한 곳에만 둔다."""
    return core.check_readiness(pins_api.count_opinion_pins(db, map_id=map_id, category=category))


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


def reason_text_inputs(raw_reactions: Sequence[Mapping[str, Any]]) -> list[dict]:
    """글이 있는 반응마다 ②에 보낼 입력(_evidence_from_reaction), 반응 순서 그대로. run 생성과 agent의 ②(api.reason_text_inputs,
    #1180)가 같이 쓴다 — ②의 결과 묶음은 이 순서와 개수 그대로 온다."""
    return [_evidence_from_reaction(r) for r in raw_reactions if r["reason_text"] is not None]


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


def _reaction_evidence_lines(raw_reactions: list[dict], planned_groups: list[list[dict]]) -> list[dict]:
    """반응마다 글 줄(②를 거친 것, 있을 때만) 다음에 칩 줄을 붙인다(#412) — 한 사람이 한 반응에 남긴 줄이
    붙어 있어야 「−」로 뺄 자기 근거를 찾기 쉽다. planned_groups는 글이 있는 반응 순서 그대로의 ② 결과이고,
    글 하나가 조건마다 줄 하나로 나뉜 묶음이다(#419) — 묶음 안 줄들이 모두 그 반응의 칩 줄보다 앞에 온다."""
    planned = iter(planned_groups)
    lines: list[dict] = []
    for reaction in raw_reactions:
        if reaction["reason_text"] is not None:
            lines.extend(next(planned))
        lines.extend(_evidence_from_chip(reaction, chip) for chip in reaction["chips"])
    return lines


def _assembled_reaction_lines(raw_reactions: list[dict], planned_groups: list[list[dict]], category: str) -> list[dict]:
    """반응과 ② 결과 → run에 넣을 근거 줄(글 줄, 칩 줄, #422·#617 내리기). run 생성(_create_run)과 미리 돌려 보기
    (preview_filter, #1180)가 같이 쓴다 — 줄 조립 규칙을 한 곳에 둔다."""
    reaction_lines = _reaction_evidence_lines(raw_reactions, planned_groups)
    return core.assemble_evidence(core.demote_wanted_place_identity(reaction_lines, category), [])  # #422, #617


def _default_circle_and_anchors(
    db: Session, *, map_id: str, category: str,
) -> tuple[Circle, list[tuple[float, float]]] | None:
    """같은 카테고리 핀 좌표와 기본 반경을 읽는다. 반환 중심은 지역 묶음을 만들기 위한 대표값이고,
    실제 후보 조회는 각 핀을 중심으로 한다(#1252). 좌표가 없으면 None이다."""
    coordinates = sorted(pins_api.get_category_pin_coordinates(db, map_id=map_id, category=category), key=lambda row: row[0])
    if not coordinates:
        return None
    anchors = [(lat, lng) for _, lat, lng in coordinates]
    center_lat = sum(lat for lat, _ in anchors) / len(anchors)
    center_lng = sum(lng for _, lng in anchors) / len(anchors)
    # 기본 반경 = 카테고리의 기본 도보 분(core.radius_walk_mins, #1055)을 common.geo 보정계수로 환산한 거리
    radius_m = core.radius_m_for_walk_min(core.radius_walk_mins(category)[0])
    circle = Circle(anchor_lat=center_lat, anchor_lng=center_lng, radius_m=radius_m)
    return circle, anchors


def _region_data(circle: Circle, *, label: str, confirmed: bool, anchor_points: list[tuple[float, float]]) -> dict:
    return {
        "signature": core.region_signature([Circle(lat, lng, circle.radius_m) for lat, lng in anchor_points] or [circle]),
        "label": label,
        "center_lat": circle.anchor_lat,
        "center_lng": circle.anchor_lng,
        "radius_m": circle.radius_m,
        "anchor_points": [[lat, lng] for lat, lng in anchor_points],
        "confirmed": confirmed,
        "confirmed_at": datetime.now(timezone.utc) if confirmed else None,
    }


def _clustered_regions(circle: Circle, anchors: Sequence[tuple[float, float]]) -> list[tuple[Circle, list[tuple[float, float]]]]:
    """기본 반경 두 배 이내로 이어진 핀마다 한 지역을 만든다."""
    points = [geo.Point(str(i), lat, lng) for i, (lat, lng) in enumerate(anchors)]
    groups = geo.cluster_points(points, circle.radius_m * 2)
    return [
        (Circle(sum(p.lat for p in group) / len(group), sum(p.lng for p in group) / len(group), circle.radius_m),
         [(p.lat, p.lng) for p in group])
        for group in groups
    ]


def create_run(
    db: Session, *, map_id: str, category: str, requested_by: str, evidence_planner: EvidencePlanGateway,
    idempotency_key: str | None = None, execute: bool = False,
    place_search: PlaceSearchGateway | None = None, place_facts: PlaceFactsGateway | None = None,
) -> RecommendRun:
    """POST /maps/{mapId}/runs. `Idempotency-Key`가 없으면 `_create_run` 그대로(구FE). 있으면 같은 키의 연타·재전송을
    한 번으로 묶는다(#811, docs/data-model.md idempotency_keys):

    1) 모델을 부르기 전에 (요청자, 키)를 **독립 트랜잭션**으로 기록하고 커밋한다. 요청 세션에 넣으면 모델 호출 전
       rollback에 사라지거나 둘째 INSERT가 첫째의 커밋까지 기다린다. 예약을 가진 요청만 모델을 부른다.
    2) 이미 있는 키: 본문(지도, category, execute)이 다르면 409 IDEMPOTENCY_CONFLICT, run이 이미 있으면 그 run의 **현재
       상태**를 돌려준다(최초 응답 복제 아님. 같은 요청자·같은 지도라 라우터의 지도 구성원 검사가 이 요청에도 이미 통과했다),
       아직 모델을 기다리는 중이면 409 REQUEST_IN_PROGRESS, 처리 기한(90초)이 지났으면 이어받는다.
    3) run_id 연결은 run을 만든 트랜잭션의 **맨 끝**에서 한다 — 자기 세대일 때만 성공하고(늦게 끝난 쪽은 거절),
       실패 정리가 이 행의 잠금과 부딪치지 않는다. run을 못 만들면 자기 세대의 예약만 지워 재시도를 허용한다."""
    traces: list[uuid.UUID] = []   # ②를 부른 trace — run이 저장되지 못하면 버려진 비용으로 표시한다(#848)

    def create() -> RecommendRun:
        with llm_api.plan_deadline():   # create 시작에서 한 번 정한 deadline — ② 묶음 호출 전체가 30초 안에 끝난다(#848)
            run = _create_run(
                db, map_id=map_id, category=category, requested_by=requested_by, evidence_planner=evidence_planner,
                traces=traces,
            )
        if execute:   # #845, #847 — 근거 조립 뒤 같은 요청·같은 트랜잭션에서 첫 검색까지. 어디서 실패하든 run·횟수·크레딧 차감이 함께 되돌아간다
            assert place_search is not None and place_facts is not None   # 호출부(라우터) 계약
            service.lock_run(db, run.id)
            _search_and_store(db, run, place_search=place_search, place_facts=place_facts, first_run=True)
        return run

    if idempotency_key is None:
        try:
            return create()
        except BaseException:
            llm_api.mark_discarded(traces)
            raise
    request_hash = core.idempotency_request_hash(map_id, category, execute)
    with Session(bind=db.get_bind()) as reservation_db:   # 요청 세션과 다른 연결 — 요청의 커밋·롤백과 무관하게 바로 보인다
        reservation = service.reserve_idempotency_key(
            reservation_db, requested_by=requested_by, key=idempotency_key, request_hash=request_hash,
            now=datetime.now(timezone.utc),
        )
        reservation_db.commit()
    if reservation.outcome == "conflict":
        raise AppError("IDEMPOTENCY_CONFLICT")
    if reservation.outcome == "in_progress":
        raise AppError("REQUEST_IN_PROGRESS")
    if reservation.outcome == "reuse":
        return service.get_run_or_404(db, str(reservation.run_id))
    try:
        run = create()
        service.link_idempotency_key(db, reservation_id=reservation.id, generation=reservation.generation, run_id=run.id)
    except BaseException:
        llm_api.mark_discarded(traces)
        with Session(bind=db.get_bind()) as release_db:
            service.release_idempotency_key(release_db, reservation_id=reservation.id, generation=reservation.generation)
            release_db.commit()
        raise
    return run


def _create_run(
    db: Session, *, map_id: str, category: str, requested_by: str, evidence_planner: EvidencePlanGateway,
    traces: list[uuid.UUID] | None = None,
) -> RecommendRun:
    """run 생성 + 근거 조립(①②) + 기본값 지역 계산까지 한 요청
    안에서 동기로 끝낸다. 순서: 1) 준비 판정(409 NOT_READY) 2) 크레딧 확인(읽기, 게스트 403·부족 402, #432)
    3) 반응 → 근거 구조화(글은 llm.api.plan_evidence, 칩은 코드 #412) 4) run INSERT + 크레딧 차감(같은 트랜잭션)
    5) evidence_lines INSERT 6) 기본값 지역 INSERT. 모델 호출(최대 15초+재시도)이 끝난 뒤에야 INSERT한다(#208) — 그동안 쓰기
    트랜잭션을 열어두지 않고, 모델이 실패하면 run 행이 남지 않는다. 뒤에서 실패해도 차감이 run과 함께 롤백되므로
    실패에는 환불 경로가 없다. 환불은 한 곳뿐이다 — 그 run의 **첫 실행이 후보 0곳**일 때 `_search_and_store`가 같은 트랜잭션에서
    돌려준다(#1015, docs/credits-reviews.md 3.3). `Idempotency-Key` 재전송은 이 함수를 다시 타지 않는다."""
    readiness = readiness_for_category(db, map_id=map_id, category=category)
    if not readiness["ready"]:
        raise AppError("NOT_READY", detail=readiness)
    credits_api.check_can_spend(db, user_id=requested_by, feature="recommend_run")   # 모델(②) 전에 막는다(#949)

    raw_reactions = pins_api.list_reasoned_reactions(db, map_id=map_id, category=category)
    # ②에는 사람이 쓴 글만 보낸다(#412) — 칩은 키·방향이 정해져 있어 코드가 줄을 만든다. 글이 없으면 ② 호출도 없다.
    text_inputs = reason_text_inputs(raw_reactions)
    if text_inputs:
        db.rollback()  # 모델을 기다리는 동안 읽기 트랜잭션이 연결을 잡고 있지 않게 한다(#275). 저장이 아니라 연결 반환이다.
    # ② — 느린 호출이라 run INSERT보다 먼저(#208). 그래서 사용량 기록(#870)에는 run_id가 없다(trace_id로 묶는다)
    with llm_api.usage_context("recommend_run", map_id=map_id, user_id=requested_by) as label:
        planned = evidence_planner.plan_evidence(text_inputs) if text_inputs else []
    if text_inputs and traces is not None:
        traces.append(label.trace_id)   # 모델은 불렸다 — 뒤 단계가 실패하면 호출자가 이 trace를 버려진 비용으로 표시한다(#848)
    merged = _assembled_reaction_lines(raw_reactions, [[line.model_dump() for line in group] for group in planned], category)

    # 번호를 읽고 INSERT하기까지는 (지도, 요청자) 횟수 잠금 안에서 끝낸다 — 동시 요청이 같은 attempt_no를 쓰지 못하게(#811).
    service.lock_requester_attempts(db, map_id=map_id, requested_by=requested_by)
    current_max = service.max_attempt_no_for_requester(db, map_id=map_id, requested_by=requested_by)
    run = service.create_run(db, map_id=map_id, category=category, requested_by=requested_by, attempt_no=current_max + 1)
    # 모델을 기다리는 사이 잔액이 줄었으면 여기서 402다(모델은 이미 불렸다 — 드문 경합으로 받아들인다, credits.api.charge)
    credits_api.charge(db, user_id=requested_by, feature="recommend_run", run_id=str(run.id))
    service.add_reaction_evidence(db, run_id=run.id, lines=merged)

    default_region = _default_circle_and_anchors(db, map_id=map_id, category=category)
    if default_region is None:
        raise AppError("NOT_READY")
    circle, anchors = default_region
    groups = _clustered_regions(circle, anchors)
    service.create_regions(db, run_id=run.id, regions_data=[
        _region_data(group_circle, label=DEFAULT_REGION_LABEL if len(groups) == 1 else f"{DEFAULT_REGION_LABEL} {i + 1:03d}",
                     confirmed=True, anchor_points=group_anchors)
        for i, (group_circle, group_anchors) in enumerate(groups)
    ])

    return run


def _evidence_response(
    line, principal: Principal, *, category: str, off_season: frozenset[str], author_names: Mapping[str, str | None],
) -> schemas.EvidenceLine:
    use = core.evidence_line_use(line.badge, line.fact_key, line.wants, category, off_season)
    resource = Resource(type="evidence_line", map_id=principal.map_id, author_id=line.author_id)
    return schemas.EvidenceLine(   # effect는 HTTP 응답에 내지 않는다(recommend.api만, #751)
        id=str(line.id), author_id=line.author_id, author_display_name=author_names.get(line.author_id),
        text=line.text, badge=line.badge,
        fact_key=line.fact_key, fact_label=constraints.FACT_LABELS.get(line.fact_key) if line.fact_key else None,
        wants=line.wants, enforced=use.enforced, not_enforced_reason=use.not_enforced_reason,
        filters_candidates=use.filters_candidates, is_active=line.is_active,
        permissions=Permissions(can_disable=can(principal, "evidence.disable", resource)),
    )


def _evidence_responses(db: Session, run: RecommendRun, principal: Principal) -> list[schemas.EvidenceLine]:
    off_season = _out_of_season_keys(db, run.map_id)
    lines = service.list_evidence(db, str(run.id))
    # 작성자 이름은 핀 작성자 규칙(#369)을 pins.api로 받아 조회할 때 계산한다(#762). 구성원 집합은 줄 수와 상관없이 한 번 구한다.
    current_member_ids = maps_api.DbMembershipGateway(db).current_member_ids(run.map_id)
    author_names = pins_api.author_display_names(db, [line.author_id for line in lines], current_member_ids)
    return [
        _evidence_response(line, principal, category=run.category, off_season=off_season, author_names=author_names)
        for line in lines
    ]


def list_evidence(db: Session, *, run_id: str, principal: Principal) -> list[schemas.EvidenceLine]:
    run = service.get_run_or_404(db, run_id)
    return _evidence_responses(db, run, principal)


def _check_manual_evidence_limit(db: Session, run_id: uuid.UUID, *, adding: int) -> None:
    """run 하나에 「+」로 추가한 글은 core.MANUAL_EVIDENCE_LIMIT개까지(뺀 것도 센다, #707). used는 이 요청 전까지의 수다."""
    used = service.count_manual_entries(db, run_id)
    if used + adding > core.MANUAL_EVIDENCE_LIMIT:
        raise AppError("EVIDENCE_LIMIT", detail={"limit": core.MANUAL_EVIDENCE_LIMIT, "used": used})


def _manual_texts_by_author(db: Session, run_id: uuid.UUID, author_id: str) -> dict[str, list]:
    """이 run에서 이 사람이 「+」로 쓴 글(정규화한 글 → 그 글의 줄들, ×로 뺀 줄 포함). 같은 글 재추가의 멱등 판정(#848)이 쓴다.
    글 하나에 조건이 여럿이면 줄이 여럿이다(#419)."""
    by_text: dict[str, list] = {}
    for line in service.list_manual_lines_by_author(db, run_id, author_id):
        by_text.setdefault(core.normalize_manual_text(line.text), []).append(line)
    return by_text


def patch_evidence(
    db: Session, *, run_id: str, principal: Principal,
    toggles: list[tuple[str, bool]], adds: list[str], evidence_planner: EvidencePlanGateway,
) -> list[schemas.EvidenceLine]:
    """PATCH /runs/{runId}/evidence (5-5). '-'는 author 본인만(evidence.disable, author-
    constrained) — 권한 없는 토글이 섞여 있으면 요청 전체를 403으로 거절한다(api-spec.yaml이
    이 엔드포인트에 Forbidden을 명시함 — "버튼이 애초에 disabled였어야 했다"는 신호)."""
    run = service.get_run_or_404(db, run_id)
    run_uuid, run_map_id = run.id, run.map_id   # 롤백 뒤에 run을 읽으면 트랜잭션이 다시 열린다 — 미리 꺼내 둔다
    # 읽기(존재·권한 검사) → 롤백 → 모델 → 쓰기 순서다(#275). 모델을 기다리는 동안 트랜잭션도 연결도 잡지 않는다.
    validated: list[tuple[uuid.UUID, bool]] = []
    for evidence_id, is_active in toggles:
        line = service.get_evidence_or_none(db, evidence_id)
        if line is None or line.run_id != run_uuid:
            raise AppError("NOT_FOUND")
        resource = Resource(type="evidence_line", map_id=principal.map_id, author_id=line.author_id)
        if not can(principal, "evidence.disable", resource):
            raise AppError("FORBIDDEN")
        validated.append((line.id, is_active))
    # 한 요청 안의 같은 글은 하나로 줄인다(공백만 다른 글도 같은 글) — 상한은 (글, 요청)으로 세므로 반복한 글이 ②에만 여러 번
    # 들어가지 않게(#707). 같은 run에서 같은 사람이 이미 쓴 글(×로 뺀 것 포함)을 다시 보내면 새 줄도 모델 호출도 글 수 상한도 없이
    # 그 줄을 그대로 돌려주고 뺀 줄이면 다시 켠다(#848). 다른 사람의 같은 글은 별개의 줄이다. 모델에는 새 글만 보낸다.
    requested = list(dict.fromkeys(core.normalize_manual_text(text) for text in adds))
    already = _manual_texts_by_author(db, run_uuid, principal.user_id)
    repeated = [text for text in requested if text in already]
    adds = [text for text in requested if text not in already]
    # 「+」 상한(#707)은 모델을 부르기 전에 본다 — 넘는 요청은 ②를 부르지 않는다.
    if adds:
        _check_manual_evidence_limit(db, run_uuid, adding=len(adds))
    # 「+」로 추가한 줄도 ②를 거쳐 fact_key·wants를 붙인다(#254) — 근거 줄에 "한식 제외"처럼 해석한 조건이
    # 보인다. 실패 시 동작은 create_run과 같다(PlanEvidenceFailed를 그대로 올린다 — 모델이 쓰기보다 먼저라 행이 안 남는다).
    # 글 하나에 조건이 여럿이면 같은 글로 조건마다 줄 하나다(#419).
    planned: list = []
    trace_id: uuid.UUID | None = None
    if adds:
        db.rollback()  # 읽기 트랜잭션을 끝내 연결을 돌려준다(#275). 저장이 아니다.
        with llm_api.usage_context("evidence_add", map_id=run_map_id, user_id=principal.user_id, run_id=str(run_uuid)) as label:
            planned = evidence_planner.plan_evidence([
                {"author_id": principal.user_id, "source": "manual", "text": text, "badge": "preferred", "fact_key": None}
                for text in adds
            ])
        trace_id = label.trace_id
    try:
        if validated or adds or repeated:
            # 위 검사들은 잠금 없이 끝났다(모델을 기다리는 동안 트랜잭션을 잡지 않는다). 같은 run에 동시에 온 요청이 함께 상한을 넘지
            # 않게 run 행을 잠그고 다시 센다 — 이때 걸리면 모델은 이미 불렸지만 줄은 남지 않는다(멘토 리뷰 #380: 여러 행에 걸친 상한).
            service.lock_run(db, run_uuid)
        # 잠근 뒤 다시 읽는다 — 모델을 기다리는 사이 같은 글이 다른 요청(연타·재전송)으로 이미 저장됐을 수 있다. 그 글은 새 줄을 더하지 않고
        # 그 줄을 쓴다(모델 결과는 버린다).
        already = _manual_texts_by_author(db, run_uuid, principal.user_id)
        planned_by_text = dict(zip(adds, planned)) if adds else {}
        to_add = [text for text in adds if text not in already]
        if to_add:
            _check_manual_evidence_limit(db, run_uuid, adding=len(to_add))
        for line_id, is_active in validated:
            service.set_evidence_active(db, line_id, is_active)
        for text in [*repeated, *(text for text in adds if text in already)]:   # 뺐던 줄이면 다시 켠다
            for line in already[text]:
                if not line.is_active:
                    service.set_evidence_active(db, line.id, True)
        for text in to_add:
            for line in planned_by_text[text]:
                service.add_manual_evidence(
                    db, run_id=run_uuid, author_id=principal.user_id, text=text, fact_key=line.fact_key, wants=line.wants,
                )
    except BaseException:
        if trace_id is not None:   # 모델은 불렸는데 저장이 안 됐다(글 수 상한 재검사 등) — 버려진 비용으로 표시한다(#848)
            llm_api.mark_discarded(trace_id)
        raise
    return _evidence_responses(db, run, principal)


def _region_response(region) -> schemas.Region:
    return schemas.Region(id=str(region.id), label=region.label, signature=region.signature, confirmed=region.confirmed)


def confirm_regions(db: Session, *, run_id: str, accept_union: bool) -> list[schemas.Region]:
    """POST /runs/{runId}/regions/confirm (5-6-1). 기본 지역 무리는 자동 확정한다.
    실제로 REGION_CONFLICT가 나는 경로가 없다 — 겹침 판정 로직 자체는
    core.circles_all_overlap/region_signature 단위 테스트로 커버한다(#274)."""
    run = service.get_run_or_404(db, run_id)
    regions = service.list_regions(db, run_id)
    unconfirmed = [r for r in regions if not r.confirmed]
    if unconfirmed and not accept_union:
        raise AppError("REGION_CONFLICT", detail={"regions": [_region_response(r).model_dump() for r in regions]})
    service.confirm_all_regions(db, run.id)
    service.set_run_status(db, run, "executing")
    return [_region_response(r) for r in service.list_regions(db, run_id)]


def _used_lines(lines: Sequence[EvidenceLineRow], category: str, off_season: Collection[str]) -> list[EvidenceLineRow]:
    """파이프라인이 실제로 쓰는 줄만(core.evidence_line_use, #740) — 근거 응답의 enforced와 같은 기준이다."""
    return [line for line in lines if core.evidence_line_use(line.badge, line.fact_key, line.wants, category, off_season)[0]]


def _hard_fact_keys_from(used_lines: Sequence[EvidenceLineRow]) -> list[str]:
    """5-6 3단계 — "활성 실격 조건"(constraints.md)만 순회한다: 쓰이는 줄 중 badge='required'이고 hard 키인 것만 켠다
    (누구도 문제 제기 안 한 조건은 검사하지 않는다). hard 키는 방향이 고정이라("있으면 실격") wants를 보지 않는다.
    ♥·「+」 사유로도 켜던 안전 조건 규칙(D11, #254)은 안전 조건 키와 함께 없앴다(#425)."""
    return sorted({
        line.fact_key for line in used_lines if line.badge == "required" and line.fact_key in constraints.HARD_REGISTRY
    })


def _soft_requirements_from(used_lines: Sequence[EvidenceLineRow]) -> list[tuple[str, bool]]:
    """접근성 원함의 required 사유만 실격 조건으로 모은다."""
    return sorted({
        (line.fact_key, line.wants) for line in used_lines
        if line.badge == "required" and line.fact_key in constraints.NEED_FILTER_SOFT_KEYS and line.wants is True
    })


def _active_hard_fact_keys(db: Session, run: RecommendRun) -> list[str]:
    off_season = _out_of_season_keys(db, run.map_id)
    return _hard_fact_keys_from(_used_lines(service.list_active_evidence(db, run.id), run.category, off_season))


def _active_soft_requirements(db: Session, run: RecommendRun) -> list[tuple[str, bool]]:
    off_season = _out_of_season_keys(db, run.map_id)
    return _soft_requirements_from(_used_lines(service.list_active_evidence(db, run.id), run.category, off_season))


def _passes_hard_check(value) -> bool:
    return not bool(value)  # is_crowded_large — "있으면 실격"류


@dataclass(frozen=True)
class _PipelineRegion:
    """_run_pipeline이 읽는 지역 값. regions 행의 사본이라 반경을 바꿔도 DB에 쓰이지 않는다(시뮬레이션, #585).
    pool_radius_m은 후보 풀을 가져오는 반경(넓히기 상한까지, #792)이고 radius_m은 「반경 밖 제거」가 보는 반경이다."""

    id: uuid.UUID | None   # 미리 돌려 보기(#1180)의 지역은 저장하지 않아 None
    label: str
    center_lat: float
    center_lng: float
    radius_m: int
    pool_radius_m: int
    anchor_points: tuple[tuple[float, float], ...]


def _trip_weekdays(db: Session, map_id: str) -> list[int]:
    """지도 여행 기간의 요일들(core.trip_weekdays, 0=월 … 6=일). 지도를 못 읽거나 날짜가 없으면 빈 목록 = 영업 판정을 안 한다."""
    info = maps_api.get_map_for_agent(db, map_id)
    if info is None:
        return []
    return core.trip_weekdays(info["start_date"], info["end_date"])


def _open_status_by_place(place_facts: PlaceFactsGateway, place_ids: Sequence[str], weekdays: Sequence[int]) -> dict[str, str]:
    """후보마다 여행 요일 기준 영업 여부("closed" | "open" | "unknown", #690). 시간 조회가 없는 게이트웨이이거나 여행 날짜가
    없으면 전부 "unknown"이다(지금처럼 아무도 빼지 않는다). 한 번에 배치 조회(N+1 금지)."""
    get_week_status = getattr(place_facts, "get_week_open_status", None)
    if not weekdays or get_week_status is None or not place_ids:
        return dict.fromkeys(place_ids, "unknown")
    week_by_place = get_week_status(list(place_ids))
    return {place_id: core.trip_open_status(week_by_place.get(place_id), weekdays) for place_id in place_ids}


def _pipeline_inputs(
    db: Session, run: RecommendRun, *, radius_factor: float | None = None, disable_line_ids: frozenset[str] = frozenset(),
) -> tuple[list[_PipelineRegion], list[EvidenceLineRow]]:
    """저장된 지역과 활성 근거 줄을 _run_pipeline 입력으로 읽는다. 실행(execute/widen/retry)은 그대로 쓰고,
    시뮬레이션(#585)만 반경 배율과 비활성으로 볼 줄을 준다 — 사본과 거른 목록이라 행은 바뀌지 않는다.
    풀 반경은 배율과 무관하게 저장된 반경 × 넓히기 상한 배율이라 시뮬레이션도 실행과 같은 풀을 쓴다(#792)."""
    pool_factor = core.pool_radius_factor(run.default_radius_walk_min, run.category)
    regions = [
        _PipelineRegion(
            id=r.id, label=r.label, center_lat=r.center_lat, center_lng=r.center_lng,
            radius_m=r.radius_m if radius_factor is None else round(r.radius_m * radius_factor),
            pool_radius_m=round(r.radius_m * pool_factor),
            anchor_points=tuple(tuple(point) for point in r.anchor_points),
        )
        for r in service.list_regions(db, str(run.id))
    ]
    active_lines = [line for line in service.list_active_evidence(db, run.id) if str(line.id) not in disable_line_ids]
    return regions, active_lines


def _within_trip_sido(
    db: Session, map_id: str, regions: Sequence[_PipelineRegion], places: list[PlaceStub], place_search: PlaceSearchGateway,
) -> list[PlaceStub]:
    """여행 지역과 다른 시·도의 후보를 뺀다(#1055, #1059) — 깔때기에서는 「반경 밖 제거」로 센다. 판정은 places.api(sido, sido_at)만
    쓴다. 여행 지역의 시·도는 지도 여행 지역 중심, 없으면 기본 지역 중심(그 카테고리 핀들의 중심)으로 이 실행에서 한 번 정한다.
    어느 한쪽이라도 None이면 거르지 않는다(모름을 실격으로 읽지 않는다). 주소는 한 번에 배치 조회(N+1 금지)."""
    infos = place_search.get_places([p.place_id for p in places]) if places else {}
    place_sido = {pid: places_api.sido(info.address) for pid, info in infos.items()}
    if not any(place_sido.values()):
        return places
    center = maps_api.get_map_region_center(db, map_id) or (
        (regions[0].center_lat, regions[0].center_lng) if regions else None
    )
    trip_sido = places_api.sido_at(*center, db=db) if center else None
    if trip_sido is None:
        return places
    return [p for p in places if place_sido.get(p.place_id) in (None, trip_sido)]


def _out_of_season_keys(db: Session, map_id: str) -> frozenset[str]:
    """이 지도의 여행 기간과 시즌이 안 겹치는 계절 키(core.out_of_season_keys). 지도를 못 읽으면 모두 쓴다."""
    info = maps_api.get_map_for_agent(db, map_id)
    if info is None:
        return frozenset()
    return core.out_of_season_keys(info["start_date"], info["end_date"])


@dataclass(frozen=True)
class _Filtered:
    """_filter_places의 결과 — 5-6 실격 필터의 앞 세 단계(반경 → 영업 종료 → 실격 조건)를 지난 곳과 그 단계가 만든 값.
    실행(_run_pipeline)은 이 뒤에 중복 제외와 순위를 잇고, 미리 돌려 보기(preview_filter, #1180)는 여기서 멈춘다."""

    active_lines: list            # 활성 줄 중 여행 기간 밖 계절 키를 뺀 것
    used_lines: list              # 그중 쓰이는 줄(core.evidence_line_use)
    hard_keys: list[str]
    soft_requirements: list[tuple[str, bool]]
    preferred_authors: dict[str, frozenset[str]]
    avoided_authors: dict[str, frozenset[str]]
    labels_by_place: dict[str, list]      # 반경·영업 단계를 지난 곳의 place_facts 라벨
    checks_by_place: dict[str, list[Check]]
    regions_by_place: dict[str, _PipelineRegion]
    passed: list[PlaceStub]               # 실격 조건까지 통과한 곳, 풀 순서
    removed: dict[str, int]               # 단계 키(pool, radius, closed, disqualify) → 이 단계에서 빠진 수


def _filter_places(
    db: Session, *, map_id: str, category: str,
    regions: Sequence[_PipelineRegion], active_lines: Sequence[Any],
    place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway, off_season: frozenset[str],
) -> _Filtered:
    """5-6 실격 필터의 앞 세 단계(반경 → 영업 종료 → 실격 조건). run을 받지 않는다 — 실행과 미리 돌려 보기(#1180)가 같은 거르기를
    부르게 입력(지도, 카테고리, 지역, 활성 근거 줄)만 받는다. 줄은 author_id, badge, fact_key, wants 칸이 있으면 된다
    (EvidenceLineRow, _DraftLine). DB에 쓰지 않는다."""
    # 상한 풀과 현재 반경을 각각 DB에서 판정해 깔때기의 넓히면 들어오는 장소 수를 유지한다.
    # 각 지역별 핀 원의 합집합이며 겹치는 후보는 첫 지역에 배정한다.
    pool_by_id: dict[str, PlaceStub] = {}
    within_by_id: dict[str, PlaceStub] = {}
    regions_by_place: dict[str, _PipelineRegion] = {}
    for region in regions:
        anchors = region.anchor_points or ((region.center_lat, region.center_lng),)
        pool_circles = [Circle(lat, lng, region.pool_radius_m) for lat, lng in anchors]
        circles = [Circle(lat, lng, region.radius_m) for lat, lng in anchors]
        for place in place_search.search_nearby(category=category, circles=pool_circles):
            pool_by_id.setdefault(place.place_id, place)
        for place in place_search.search_nearby(category=category, circles=circles):
            if place.place_id not in within_by_id:
                within_by_id[place.place_id] = place
                regions_by_place[place.place_id] = region
    pool = list(pool_by_id.values())
    within_radius = list(within_by_id.values())
    within_radius = _within_trip_sido(db, map_id, regions, within_radius, place_search)
    removed_radius = len(pool) - len(within_radius)

    # 영업 종료 제거(#690) — 여행 기간의 모든 요일이 휴무인 장소만 뺀다. 하루라도 영업하면 통과, 정보가 없으면 통과 +
    # 「영업 여부 확인 필요」. 여행 날짜가 없거나 시간 조회가 없으면 아무도 안 뺀다(공휴일·closed_note는 보지 않는다).
    open_status = _open_status_by_place(place_facts, [p.place_id for p in within_radius], _trip_weekdays(db, map_id))
    open_places = [p for p in within_radius if open_status[p.place_id] != "closed"]
    removed_open = len(within_radius) - len(open_places)
    within_radius = open_places
    unknown_open_check = core.build_check("is_open", "pass", known=False, value=None, passes=True)
    known_open_check = core.build_check("is_open", "pass", known=True, value=True, passes=True)

    # 계절 키는 여행 기간이 시즌과 겹칠 때만 쓴다(#681-6) — 시즌 밖이면 직접 쓴 사유도 이번 실행에서 없는 셈 친다(점수 0,
    # 후보를 거르지 않고, 이유·체크에도 안 나온다). 날짜가 없으면 모두 쓴다.
    active_lines = [line for line in active_lines if line.fact_key not in off_season]
    # 아래 조건·점수는 쓰이는 줄(core.evidence_line_use)에서만 만든다 — 근거 응답의 enforced와 같은 기준이다(#740).
    used_lines = _used_lines(active_lines, category, off_season)
    active_hard_keys = _hard_fact_keys_from(used_lines)
    soft_requirements = _soft_requirements_from(used_lines)
    preferred_authors: dict[str, set[str]] = {}
    avoided_authors: dict[str, set[str]] = {}  # soft + wants=false — 점수에서 반대 구성원
    for line in used_lines:
        # wants=None(방향을 모름)인 선호는 쓰이는 줄이 아니라 지지·반대 어디에도 세지 않는다 — 효과 없음(constraints.md 표, #237).
        if (line.badge in ("preferred", "required") and line.fact_key in constraints.SOFT_FACT_KEYS
                and (line.fact_key, line.wants) not in soft_requirements):
            by_direction = preferred_authors if line.wants else avoided_authors
            by_direction.setdefault(line.fact_key, set()).add(line.author_id)
    # 선호 라벨 체크는 이 카테고리에 적용되는 키 + 사람이 직접 원한 키만 붙인다 — 50여 개를 전부 붙이면
    # 「확인 필요」 체크가 넘치고, 원하지 않은 키는 어차피 점수에 쓰이지 않는다.
    soft_keys = sorted(
        set(constraints.soft_fact_keys_for(category))
        | (constraints.SOFT_FACT_KEYS & (preferred_authors.keys() | avoided_authors.keys()))
        | {fact_key for fact_key, _wants in soft_requirements}
    )
    # ③-a-1 — 라벨은 자체 DB(place_facts)에서 읽는다. 요청 중 모델을 부르지 않는다(#190, v1). 없는 라벨은
    # confidence=unknown으로 보고 unknown_policy를 그대로 적용한다. 한 번에 배치 조회(N+1 금지).
    facts_by_place = place_facts.get_facts([p.place_id for p in within_radius])
    checks_by_place: dict[str, list[Check]] = {}
    for place in within_radius:
        labels = facts_by_place.get(place.place_id, [])
        checks = [known_open_check if open_status[place.place_id] == "open" else unknown_open_check]
        for fact_key in active_hard_keys:
            known, value = core.resolve_label(labels, fact_key)
            passes = _passes_hard_check(value) if known else True
            checks.append(core.build_check(
                fact_key, constraints.HARD_REGISTRY[fact_key].unknown_policy, known=known, value=value, passes=passes,
            ))
        # #112 1단계 입력 — 선호(soft) 라벨도 같이 붙인다. unknown_policy는 표 그대로 "pass"
        # 고정(constraints.md — 순위에서 중립 처리). passed는 hard 체크처럼 "실격 아님"이 아니라
        # 그 라벨의 실제 참/거짓값이다.
        for fact_key in soft_keys:
            known, value = core.resolve_label(labels, fact_key)
            checks.append(core.build_check(fact_key, "pass", known=known, value=value, passes=bool(value)))
        checks_by_place[place.place_id] = checks

    pass_flags = core.apply_disqualifier_filters([checks_by_place[p.place_id] for p in within_radius], soft_requirements)
    after_disqualify = [p for p, ok in zip(within_radius, pass_flags) if ok]
    return _Filtered(
        active_lines=active_lines, used_lines=used_lines, hard_keys=active_hard_keys,
        soft_requirements=soft_requirements,
        preferred_authors={key: frozenset(authors) for key, authors in preferred_authors.items()},
        avoided_authors={key: frozenset(authors) for key, authors in avoided_authors.items()},
        labels_by_place={p.place_id: facts_by_place.get(p.place_id, []) for p in within_radius},
        checks_by_place=checks_by_place, regions_by_place=regions_by_place, passed=after_disqualify,
        removed={"pool": 0, "radius": removed_radius, "closed": removed_open,
                 "disqualify": len(within_radius) - len(after_disqualify)},
    )


def _run_pipeline(
    db: Session, run: RecommendRun, *,
    regions: Sequence[_PipelineRegion], active_lines: Sequence[EvidenceLineRow],
    place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway, excluded_place_ids: set[str],
    off_season: frozenset[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """5-6 실격 필터 순서(반경→영업종료→실격조건→중복제외→정렬)를 그대로 지킨다
    (recommend/CLAUDE.md "넘지 말 것" — 순서가 funnel 표의 의미를 결정한다). 앞 세 단계는 _filter_places(미리 돌려 보기와 같은
    함수, #1180)이고 여기서는 중복 제외와 순위를 잇는다. 지역과 활성 근거 줄은 인자로 받는다(_pipeline_inputs, #585) — 이 함수는
    DB에 쓰지 않아 시뮬레이션이 입력만 바꿔 그대로 다시 돌린다."""
    # `off_season`은 실행(_search_and_store)이 한 번 계산해 넘긴다 — 파이프라인과 스냅샷이 같은 판정을 쓰게(#847). 안 넘기는
    # 호출(시뮬레이션)은 여기서 읽는다.
    if off_season is None:
        off_season = _out_of_season_keys(db, run.map_id)
    filtered = _filter_places(
        db, map_id=run.map_id, category=run.category, regions=regions, active_lines=active_lines,
        place_search=place_search, place_facts=place_facts, off_season=off_season,
    )
    active_lines = filtered.active_lines
    used_lines = filtered.used_lines
    active_hard_keys = filtered.hard_keys
    soft_requirements = filtered.soft_requirements
    checks_by_place = filtered.checks_by_place
    preferred_authors_frozen = filtered.preferred_authors
    avoided_authors_frozen = filtered.avoided_authors
    # 구성원별 반대 조건 — 충족 집계에 센다(#255, #620). 이번 실행이 실제로 확인하는 키만 넣는다: 카테고리에 맞는 hard 키
    # (방향 고정이라 wants=None)와 방향이 있는 soft 요구. 키 없는 줄(알러지 글, 「취향이 아니에요」)은 넣지 않는다.
    disqualifier_conditions: dict[str, set[tuple[str, bool | None]]] = {}
    for line in used_lines:
        if line.badge != "required":
            continue
        condition = (line.fact_key, None) if line.fact_key in constraints.HARD_REGISTRY else (line.fact_key, line.wants)
        disqualifier_conditions.setdefault(line.author_id, set()).add(condition)
    # 충족 집계의 conditions[]에 붙일 근거 줄 id(#805) — 조건을 만든 줄만: 쓰이는 required 줄, 원함 방향 preferred 줄. 실격이 먼저.
    written_line_ids: dict[tuple[str, str], str] = {}
    for line in sorted(used_lines, key=lambda used: used.badge != "required"):
        if line.badge == "required" or (line.badge == "preferred" and line.wants):
            written_line_ids.setdefault((line.author_id, line.fact_key), str(line.id))

    after_disqualify = filtered.passed
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
    # 음식점은 ♥를 누른 이유로 보기 어려운 라벨(체인점·주차 등)을 여기서 한 번 거른다(#414). 걸러진 목록을 기준·점수·충족
    # 집계·이유에 똑같이 쓴다 — 직접 쓴 선호 사유(preferred_authors)는 거르지 않는다.
    hearted_places = core.filter_heart_signals([
        core.HeartedPlace(
            checks=[c for c in core.label_checks(liked_facts.get(entry["place_id"], [])) if c.fact_key not in off_season],
            member_ids=frozenset(entry["member_ids"]),
        )
        for entry in liked_pins
    ], run.category)
    criteria = core.build_preference_criteria(
        hearted_places,
        disqualifying_fact_keys=[*active_hard_keys, *{key for key, _ in soft_requirements}],
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
    required_soft_keys = {line.fact_key for line in used_lines
                          if line.badge == "required" and line.fact_key in constraints.SOFT_FACT_KEYS}
    weights = core.preference_weights(hearted_places, criteria, preferred_authors_frozen, avoided_authors_frozen)
    anchor_points_by_region = {region.label: list(region.anchor_points) for region in regions}
    scores = core.score_candidates(
        {p.place_id: checks_by_place[p.place_id] for p in after_exclusions}, hearted_places, criteria,
        preferred_authors_frozen, avoided_authors_frozen,
    )
    scored = [
        core.ScoredCandidate(place_id=p.place_id, score=scores[p.place_id], region_label=filtered.regions_by_place[p.place_id].label, lat=p.lat, lng=p.lng)
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
            checks, hearted_places, criteria, preferred_authors_frozen, disqualifier_conditions,
            written_line_ids,
        )
        candidates_data.append({
            "place_id": place_id, "region_id": filtered.regions_by_place[place_id].id, "lat": place.lat, "lng": place.lng,
            "rank": index + 1,
            "checks": [
                check.model_dump()
                for check in core.limit_preference_checks(
                    core.to_satisfaction_checks(core.checks_to_show(checks, wanted_soft_keys), directions),
                    required_soft_keys=required_soft_keys, weights=weights,
                )
            ],
            "member_fulfillment": fulfillment,
            "reason": core.build_reason(checks, criteria),
            "place_source": dict(place.source) if place.source else None,
        })
    funnel = core.funnel_counts({
        **filtered.removed,
        "excluded": removed_exclusions,
        "ranking": removed_ranking,
    })
    return candidates_data, funnel


def _candidates_ready_event(
    db: Session, run: RecommendRun, candidates: list[CandidateRow], place_search: PlaceSearchGateway,
) -> Event:
    """docs/events.md run.candidates_ready — 스펙의 Candidate 모양 그대로(#241). 받는 사람은 요청자 본인
    하나라 permissions도 그 사람 기준으로 만든다(응답과 같은 _candidate_response)."""
    requester = Principal(user_id=run.requested_by, map_id=run.map_id, role="member")
    region_labels = {r.id: r.label for r in service.list_regions(db, str(run.id))}
    places = place_search.get_places([c.place_id for c in candidates]) if candidates else {}
    payload = {
        "run_id": str(run.id),
        "candidates": [
            _candidate_response(c, run, requester, region_labels, places).model_dump(exclude_none=True)
            for c in candidates
        ],
    }
    return Event(map_id=run.map_id, channel="private", type="run.candidates_ready",
                 payload=payload, recipient_user_id=run.requested_by)


def _excluded_place_ids(db: Session, run: RecommendRun, *, record_dismissed: bool = True) -> set[str]:
    """후보에서 뺄 place_id 전부(가드레일 6). 세 갈래를 합친다:
    1) exclusions의 `proposed`(다시 추천 받기로 이미 제안한 곳)·`dismissed`
    2) 요청자가 🚫한 핀의 장소 — 이 호출에서 `dismissed`로 exclusions에 쌓는다(#119). 핀이 지워진
       뒤에도 거절 이력이 남도록 pins가 삭제된 핀까지 돌려준다. add_exclusions는 이미 있는
       조합을 건너뛰므로 여러 번 불러도 안전하다(이미 proposed인 곳은 그대로 둔다).
       시뮬레이션(#585)은 record_dismissed=False로 쌓지 않고 집합에만 합친다 — 결과 집합은 같다.
    3) 이미 이 지도에 있는 핀(수동이든 게시된 것이든) — 안 빼면 게시하려는 순간 pins.unique(map_id,
       place_id)에 걸려 PIN_DUPLICATE(409)만 반복된다(루트 수정, 2026-09-23).
    4) 이 지도의 실시간 핀이 가리키는 가게(#569) — 실시간 핀은 place_id가 없고 카카오 ID만 있어 3)에 안 잡힌다.
       그 카카오 ID로 매칭된 자체 DB 장소를 찾아 합친다. 깔때기에서는 「이미 제안·거절됨」에 같이 센다."""
    disliked = pins_api.list_disliked_place_ids(db, user_id=run.requested_by, map_id=run.map_id, category=run.category)
    if record_dismissed:
        service.add_exclusions(
            db, map_id=run.map_id, category=run.category, place_ids=disliked,
            reason="dismissed", run_id=run.id, requested_by=run.requested_by,
        )
    live_pin_place_ids = {
        candidate.place_id
        for kakao_id in pins_api.list_live_kakao_place_ids(db, map_id=run.map_id)
        for candidate in places_api.own_places_by_kakao_id(kakao_id, db=db)
    }
    return service.list_excluded_place_ids(
        db, map_id=run.map_id, requested_by=run.requested_by,
    ) | set(disliked) | pins_api.list_place_ids_on_map(db, map_id=run.map_id) | live_pin_place_ids


def _search_and_store(
    db: Session, run: RecommendRun, *, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
    first_run: bool = False,
) -> RecommendRun:
    """execute·widen·retry·최초 실행(create_run execute=true)이 같이 쓰는 꼬리 — 제외목록을 읽고, 저장된 지역·활성 근거로
    파이프라인을 돌려 게시 안 된 후보를 교체하고, 깔때기·**실행 스냅샷**(applied_evidence, new_count, #847)을 저장해 done으로
    만든다. 스냅샷은 이 실행이 쓴 근거(활성 줄, enforced 포함)와 새로 찾은 후보 수라 이후에 근거를 고쳐도 이 결과의 설명은
    그대로다. 호출부가 run을 잠근 뒤 부른다(#811).

    run에 고정되는 입력은 구조화한 근거 줄과 기본 지역이고, 실행마다 다시 읽는 입력은 ♥ 선호·여행 날짜 판정·제외목록이다
    (docs/api-spec.yaml retry 설명).

    first_run은 이 run의 **첫 실행**일 때만 참이다(create_run execute=true, 한 번도 실행하지 않은 run의 execute). 첫 실행이 후보를
    하나도 못 찾으면(NO_RESULTS와 같은 기준) 같은 트랜잭션에서 크레딧을 환불한다(#1015, docs/credits-reviews.md 3.3). retry·widen은
    first_run이 아니라 절대 환불하지 않는다 — 처음부터 차감이 없고, 첫 실행이 결과를 냈다면 그 차감은 그대로다."""
    excluded = _excluded_place_ids(db, run)
    regions, active_lines = _pipeline_inputs(db, run)
    off_season = _out_of_season_keys(db, run.map_id)   # 실행마다 한 번 — 파이프라인이 적용한 계절 판정과 스냅샷이 어긋나지 않게
    candidates_data, funnel = _run_pipeline(
        db, run, regions=regions, active_lines=active_lines,
        place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded, off_season=off_season,
    )
    candidates = service.replace_unpublished_candidates(db, run_id=run.id, candidates_data=candidates_data)
    service.set_last_funnel(db, run, funnel)
    service.set_run_outcome(
        db, run, applied_evidence=core.applied_evidence_entries(active_lines, run.category, off_season),
        new_count=len(candidates),
    )
    service.set_run_status(db, run, "done")
    record_event(db, _candidates_ready_event(db, run, candidates, place_search))
    if first_run and not service.list_candidates(db, str(run.id)):   # 첫 실행이라 게시된 후보는 없다 — 0곳이면 쓴 크레딧을 돌려준다
        credits_api.refund(db, feature="recommend_run", run_id=str(run.id))   # 멱등(원장 ref_id UNIQUE), 잔액 상한까지만 채운다
    return run


def execute_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> RecommendRun:
    """POST /runs/{runId}/execute — 실격 필터(③-a-2) + 선호 순위(③-b) + 대안 반영(④). 첫 실행 전에 멈춘
    `collecting_evidence` run(과거 데이터, 장애)도 이 호출로 이어서 실행한다(#845)."""
    run = service.get_run_or_404(db, run_id)
    service.lock_run(db, run.id)   # 같은 run의 다른 실행과 후보 교체를 직렬화한다(#811)
    # 한 번도 실행이 끝나지 않은 run — 0곳이면 환불(#1015). 상태(collecting_evidence 등)로 판정하지 않는다: 지역 확인(confirm_regions)이 검색 없이
    # 상태를 executing으로 바꾸고, 실패한 실행은 롤백돼 상태가 그대로이기 때문이다. 실행이 끝났다는 기록(last_new_count)과 후보 유무만 본다.
    first_run = run.last_new_count is None and not service.list_candidates(db, str(run.id))
    return _search_and_store(db, run, place_search=place_search, place_facts=place_facts, first_run=first_run)


def widen_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> RecommendRun:
    """POST /runs/{runId}/widen (5-6-1, 가드레일4) — 기본값 원을 +5분(도보) 넓힌다. 카테고리 상한(core.radius_walk_mins)에
    이미 닿았으면 409 WIDEN_LIMIT(core.next_default_radius_walk_min). v1은 사람이 명시한 원과
    기본값 원을 구분할 방법이 없어 — 반경 사유가 구조화되기 전이라 명시적 원이 저장되지 않는다 —
    저장된 원 전부가 기본값 원이다. 명시적 원이 생기면 그 원은 여기서 건드리지 않도록 좁혀야
    한다(docs/constraints.md "반경 넓히기 상수", #274)."""
    run = service.get_run_or_404(db, run_id)
    service.lock_run(db, run.id)   # 같은 run의 다른 실행과 후보 교체를 직렬화한다(#811)
    regions = service.list_regions(db, run_id)
    if not regions:
        raise AppError("NOT_READY")
    next_walk_min = core.next_default_radius_walk_min(run.default_radius_walk_min, run.category)  # 409 WIDEN_LIMIT
    radius_m = core.radius_m_for_walk_min(next_walk_min)
    for region in regions:
        anchors = region.anchor_points or [[region.center_lat, region.center_lng]]
        widened = [Circle(lat, lng, radius_m) for lat, lng in anchors]
        service.update_region_radius(db, region, radius_m=radius_m, signature=core.region_signature(widened))
    service.set_default_radius_walk_min(db, run, next_walk_min)

    service.set_run_status(db, run, "executing")
    return _search_and_store(db, run, place_search=place_search, place_facts=place_facts)


def retry_run(
    db: Session, *, run_id: str, place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> RecommendRun:
    """POST /runs/{runId}/retry (3절) — 현재 뜬(아직 게시 안 된) 대안 전체를 제외목록에
    넣고 새로 찾는다. 모델을 부르지 않아 크레딧을 쓰지 않고 횟수 상한도 없다(#432 D5, #949)."""
    run = service.get_run_or_404(db, run_id)
    service.lock_run(db, run.id)   # run 먼저, 그다음 횟수 잠금(교착 방지 순서, service.lock_run)
    service.lock_requester_attempts(db, map_id=run.map_id, requested_by=run.requested_by)

    current_candidates = service.list_candidates(db, run_id)
    unpublished_place_ids = [c.place_id for c in current_candidates if c.published_pin_id is None]
    service.add_exclusions(
        db, map_id=run.map_id, category=run.category, place_ids=unpublished_place_ids,
        reason="proposed", run_id=run.id, requested_by=run.requested_by,
    )
    service.bump_attempt_no(db, run)
    return _search_and_store(db, run, place_search=place_search, place_facts=place_facts)


def simulate_filter(
    db: Session, *, run_id: str, radius_factor: float | None, disable_line_ids: Collection[str],
    place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> dict:
    """추천 막힘 조언(docs/agent-v2.md 9절, #585)의 "이 조건을 바꾸면 몇 곳이 남는가". 필터를 다시 구현하지 않고
    _run_pipeline을 입력만 바꿔 두 번 돌린다 — before는 저장된 지역·활성 근거 줄 그대로, after는 반경에
    radius_factor를 곱하고 disable_line_ids를 비활성으로 본다. 제외 목록(가드레일 6)은 실행 때와 같은 집합이다.
    **쓰지 않는다**: run·후보·근거 줄·지역·제외 목록·last_funnel을 바꾸지 않고 이벤트도 남기지 않는다.
    없는 run이나 그 run의 근거 줄이 아닌 id는 NOT_FOUND, radius_factor가 0 이하이거나 넓히기 상한을 넘으면 ValueError —
    풀이 상한까지라(#792) 상한 밖은 셀 수 없고, 상한을 넘겨 완화하는 일도 없다(가드레일 4)."""
    if radius_factor is not None and not radius_factor > 0:
        raise ValueError(f"radius_factor는 0보다 커야 한다: {radius_factor}")
    run = service.get_run_or_404(db, run_id)
    if radius_factor is not None and radius_factor > core.pool_radius_factor(run.default_radius_walk_min, run.category):
        raise ValueError(f"radius_factor가 넓히기 상한을 넘는다: {radius_factor}")
    try:
        disabled = frozenset(str(uuid.UUID(str(line_id))) for line_id in disable_line_ids)
    except ValueError:
        raise AppError("NOT_FOUND") from None
    if not disabled <= {str(line.id) for line in service.list_evidence(db, str(run.id))}:
        raise AppError("NOT_FOUND")
    excluded = _excluded_place_ids(db, run, record_dismissed=False)

    def outcome(**changes) -> dict:
        regions, active_lines = _pipeline_inputs(db, run, **changes)
        candidates_data, funnel = _run_pipeline(
            db, run, regions=regions, active_lines=active_lines,
            place_search=place_search, place_facts=place_facts, excluded_place_ids=excluded,
        )
        return {
            "result_count": len(candidates_data), "funnel": core.keyed_funnel(funnel),
            "passed_count": core.passed_count(len(candidates_data), funnel),
        }

    return {"before": outcome(), "after": outcome(radius_factor=radius_factor, disable_line_ids=disabled)}


@dataclass(frozen=True)
class _DraftLine:
    """run 없이 조립한 근거 줄 — _filter_places가 읽는 칸만(EvidenceLineRow와 같은 이름). 저장하지 않는다."""

    author_id: str
    badge: str
    fact_key: str | None
    wants: bool | None


def _planned_group(reaction: dict, text_lines: Mapping[str, Sequence[Mapping[str, Any]]]) -> list[dict]:
    """글이 있는 반응 하나의 ② 결과를 run 생성 때와 같은 줄 모양으로(_evidence_from_reaction의 작성자·출처·글 + ②의 키, 방향,
    배지). ② 결과가 없으면 ValueError — 그 반응을 빼고 세면 run과 다른 수가 된다."""
    if reaction["reaction_id"] not in text_lines:
        raise ValueError("② 결과가 없는 글 반응이 있다")
    base = _evidence_from_reaction(reaction)
    return [
        {**base, "fact_key": line["fact_key"], "wants": line.get("wants"), "badge": line["badge"]}
        for line in text_lines[reaction["reaction_id"]]
    ]


def _all_labels_true(labels: Sequence, fact_keys: Sequence[str]) -> bool:
    """라벨이 확실하고(known) 참인 키만 센다(절충안, #1180). 모르는 키가 하나라도 있으면 세지 않는다 — 약속하지 않는 쪽으로."""
    return all(known and bool(value) for known, value in (core.resolve_label(labels, key) for key in fact_keys))


def preview_filter(
    db: Session, *, map_id: str, category: str, text_lines: Mapping[str, Sequence[Mapping[str, Any]]],
    with_keys: Sequence[str] = (), place_search: PlaceSearchGateway, place_facts: PlaceFactsGateway,
) -> dict:
    """미리 돌려 보기(docs/agent-v2.md 6.7, #1180) — 지금 「추천 받기」를 누르면 실격 조건까지 남는 곳의 수. run을 만들 때와
    같은 함수로 줄을 조립하고(_assembled_reaction_lines: 칩 줄, #422·#617 내리기) 같은 지역(_default_circle_and_anchors)과 같은
    거르기(_filter_places: 반경 → 영업 종료 → 실격 조건, 시·도 제한, 여행 날짜 휴무, evidence_line_use)를 쓴다.

    반응은 run과 같이 pins.api에서 이 카테고리의 사유 있는 반응 전부를 읽는다. 글의 ②는 부르지 않고 `text_lines`(reaction_id →
    ② 결과 줄 [{fact_key, wants, badge}])로 받는다 — 모델을 부르지 않아 세션을 들고 기다리는 일이 없다. 글 반응의 ② 결과가 빠졌으면
    ValueError. 추천 대상이 아닌 카테고리는 ValueError, 추천 준비(⓪)가 안 됐거나 좌표 있는 핀이 없으면 run처럼 AppError NOT_READY.

    **읽기 전용이다.** run, 후보, 근거 줄, 지역, 제외 목록을 만들지도 읽지도 않는다 — 제외 목록은 사람마다 따로라 비공개다
    (agent-v2 2절 2번). 그래서 실제 추천은 이 수보다 적을 수 있다. 돌려주는 것은 수뿐이다 — 장소 이름과 id는 없다(크레딧 없이
    추천을 받는 길을 막는다, #432):
    `{passed_count, with_keys_count, funnel[{key, removed_count}]}`. funnel은 pool·radius·closed·disqualify 네 단계(run의 깔때기와
    같은 값, pool은 run처럼 0). with_keys_count는 통과한 곳 중 with_keys의 라벨이 모두 참(known)인 곳의 수, with_keys가 없으면 None."""
    if category not in categories.recommendable():
        raise ValueError(f"추천 대상이 아닌 카테고리: {category}")
    readiness = readiness_for_category(db, map_id=map_id, category=category)
    if not readiness["ready"]:
        raise AppError("NOT_READY", detail=readiness)
    default_region = _default_circle_and_anchors(db, map_id=map_id, category=category)
    if default_region is None:
        raise AppError("NOT_READY")
    circle, anchors = default_region
    pool_factor = core.pool_radius_factor(core.radius_walk_mins(category)[0], category)   # 새 run의 기본 반경과 같다
    groups = _clustered_regions(circle, anchors)
    regions = [
        _PipelineRegion(id=None, label=DEFAULT_REGION_LABEL if len(groups) == 1 else f"{DEFAULT_REGION_LABEL} {i + 1:03d}",
                        center_lat=c.anchor_lat, center_lng=c.anchor_lng, radius_m=c.radius_m,
                        pool_radius_m=round(c.radius_m * pool_factor), anchor_points=tuple(group_anchors))
        for i, (c, group_anchors) in enumerate(groups)
    ]
    raw_reactions = pins_api.list_reasoned_reactions(db, map_id=map_id, category=category)
    planned = [_planned_group(r, text_lines) for r in raw_reactions if r["reason_text"] is not None]
    lines = [
        _DraftLine(author_id=line["author_id"], badge=line["badge"], fact_key=line.get("fact_key"), wants=line.get("wants"))
        for line in _assembled_reaction_lines(raw_reactions, planned, category)
    ]
    filtered = _filter_places(
        db, map_id=map_id, category=category, regions=regions, active_lines=lines,
        place_search=place_search, place_facts=place_facts, off_season=_out_of_season_keys(db, map_id),
    )
    keys = list(dict.fromkeys(with_keys))
    return {
        "passed_count": len(filtered.passed),
        "with_keys_count": sum(
            _all_labels_true(filtered.labels_by_place[p.place_id], keys) for p in filtered.passed
        ) if keys else None,
        "funnel": [
            {"key": key, "removed_count": filtered.removed[key]} for key, _label in core.FUNNEL_STAGES if key in filtered.removed
        ],
    }


def _candidate_response(
    candidate: CandidateRow, run: RecommendRun, principal: Principal, region_labels: dict, places: Mapping[str, PlaceInfo],
) -> schemas.Candidate:
    resource = Resource(type="candidate", map_id=run.map_id, author_id=run.requested_by)
    # can()은 역할·작성자만 본다(published_pin_id 같은 candidate 상태를 모른다) — 이미 게시된
    # candidate에도 can_publish=true가 나가면 FE가 게시 버튼을 계속 활성 상태로 그린다(루트가
    # docs/data-model.md에 미리 남겨둔 주의사항, #57/#64 처리 중 발견 — #108 구현이 놓쳐서
    # 여기서 직접 고친다). 게시 여부는 이 함수가 이미 알고 있으니 여기서 같이 확인한다.
    already_published = candidate.published_pin_id is not None
    place = places.get(candidate.place_id)
    return schemas.Candidate(
        id=str(candidate.id), place_name=place.name if place else None, region_label=region_labels.get(candidate.region_id),
        lat=candidate.lat, lng=candidate.lng,
        rank=candidate.rank, checks=[Check(**c) for c in candidate.checks],
        reason=candidate.reason,
        member_fulfillment=candidate.member_fulfillment or None,  # {} = 집계 없음 → 필드 생략
        place_source=candidate.place_source,
        place_url=places_api.place_link(place) if place else None,
        visibility="published" if already_published else "private",
        published_pin_id=str(candidate.published_pin_id) if already_published else None,
        permissions=Permissions(
            can_publish=(not already_published) and can(principal, "recommend.publish", resource)
        ),
    )


def _applied_evidence_responses(db: Session, run: RecommendRun, principal: Principal) -> list[schemas.EvidenceLine]:
    """저장된 실행 스냅샷(applied_evidence)을 응답 모양으로 — enforced·사유는 실행 때 값 그대로다. 작성자 이름과 permissions는
    조회하는 지금 기준이다(이름은 탈퇴·나간 사람 규칙 #369/#762, can_disable은 본인 줄만)."""
    entries = run.applied_evidence or []
    current_member_ids = maps_api.DbMembershipGateway(db).current_member_ids(run.map_id)
    author_names = pins_api.author_display_names(db, [entry["author_id"] for entry in entries], current_member_ids)
    responses = []
    for entry in entries:
        resource = Resource(type="evidence_line", map_id=principal.map_id, author_id=entry["author_id"])
        responses.append(schemas.EvidenceLine(
            id=entry["id"], author_id=entry["author_id"], author_display_name=author_names.get(entry["author_id"]),
            text=entry["text"], badge=entry["badge"], fact_key=entry["fact_key"],
            fact_label=constraints.FACT_LABELS.get(entry["fact_key"]) if entry["fact_key"] else None,
            wants=entry["wants"], enforced=entry["enforced"], not_enforced_reason=entry["not_enforced_reason"],
            filters_candidates=entry.get("filters_candidates"),   # 이 값이 생기기 전 스냅샷은 null
            is_active=entry["is_active"], permissions=Permissions(can_disable=can(principal, "evidence.disable", resource)),
        ))
    return responses


def _applied_evidence_fields(db: Session, run: RecommendRun, principal: Principal) -> dict:
    """RecommendResult와 NO_RESULTS detail이 같이 싣는 스냅샷 필드(#845). 스냅샷이 없는 예전 run은 빈 dict라 필드를 생략한다."""
    if run.applied_evidence is None:
        return {}
    return {
        "applied_evidence": _applied_evidence_responses(db, run, principal),
        "no_applied_conditions": core.no_applied_conditions(run.applied_evidence),
        **({"new_count": run.last_new_count} if run.last_new_count is not None else {}),
    }


def get_result(
    db: Session, *, run_id: str, principal: Principal, place_search: PlaceSearchGateway,
) -> schemas.RecommendResult:
    """GET /runs/{runId}/result — funnel은 마지막 execute/widen/retry가 저장해둔 값을 그대로
    쓴다(재계산하지 않는다 — GET은 부작용이 없어야 한다). 후보가 schemas.FEW_RESULTS곳 미만이면 카카오맵 검색 링크를
    싣는다(0곳이면 NO_RESULTS detail, #798) — 검색어는 지금 활성 근거 줄로 만든다.

    후보는 이전에 지도에 올린 것(visibility=published)을 포함한다. NO_RESULTS는 게시 후보까지 합쳐 후보가 하나도 없을 때만
    나고(#845), 이번 검색이 0건이어도 게시 후보가 남아 있으면 200이고 new_count가 0이다. applied_evidence(이번 결과에 쓴 근거),
    no_applied_conditions, new_count는 마지막 실행의 스냅샷이다(NO_RESULTS detail에도 같은 값). 읽기 전에 run 행을 FOR SHARE로
    잠가 진행 중인 실행이 끝난 뒤의 값만 본다(service.lock_run_shared)."""
    run = service.get_run_or_404(db, run_id)
    service.lock_run_shared(db, run.id)   # 진행 중인 실행의 커밋을 기다린 뒤 읽는다 — run 행·후보·스냅샷이 같은 실행의 것이다(#848)
    if run.status != "done":
        raise AppError("RUN_NOT_FINISHED", detail={"status": run.status})  # #469 — 결과는 done일 때만 있다
    regions = service.list_regions(db, run_id)
    region_labels = {r.id: r.label for r in regions}
    candidates = service.list_candidates(db, run_id)
    funnel = core.keyed_funnel(run.last_funnel or [])   # 키는 응답에서만 붙인다(#1146)
    snapshot = _applied_evidence_fields(db, run, principal)
    if not candidates:
        external = _run_external_search(db, run, place_search)
        detail = {"funnel": funnel, "external_search": external.model_dump()}
        if snapshot:
            detail["applied_evidence"] = [line.model_dump(mode="json", exclude_none=True) for line in snapshot["applied_evidence"]]
            detail["no_applied_conditions"] = snapshot["no_applied_conditions"]
        raise AppError("NO_RESULTS", detail=detail)
    # 후보 이름과 링크는 places(자체 DB)에서 온다 — candidates에는 place_id·좌표만 저장한다(#190).
    places = place_search.get_places([c.place_id for c in candidates])
    return schemas.RecommendResult(
        run_id=str(run.id),
        funnel=[schemas.FunnelEntry(**entry) for entry in funnel],
        regions=[_region_response(r) for r in regions],
        candidates=[_candidate_response(c, run, principal, region_labels, places) for c in candidates],
        external_search=_run_external_search(db, run, place_search) if len(candidates) < schemas.FEW_RESULTS else None,
        **snapshot,
    )
