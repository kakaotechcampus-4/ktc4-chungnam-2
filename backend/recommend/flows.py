"""
「지도에 올리기」 — mentor-review-plan.md 결정. 순서와 실패 처리만 담당한다, 판단은
각 모듈 core.py/authz에 있다. 커밋하지 않는다(common/database.py get_db가 요청당
한 번 커밋한다).

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

**두 번째 차이 — 이벤트 타입(for_Root.md에 pins 버그로 보고)**: `pins.api.create_ai_pin`이
반환하는 `mutation.event`는 `pins.core.pin_created_event(pin)`가 만든 것이라 `type`이
`"pin.created"`다. 그런데 `docs/events.md`(전체 채널 표)는 「지도에 올리기」의 이벤트 타입을
`"pin.published"`로 못박아뒀다 — `create_ai_pin`은 docstring에 "recommend의 후보 게시 전용"
이라고 스스로 밝히고 있으니 이 함수가 만드는 이벤트는 애초에 `pin.published`였어야 한다.
pins.api.py를 직접 고치는 건 이 세션 범위 밖(다른 모듈 소유 파일)이라, 여기서는 payload는
그대로 재사용하고 `type`만 `pin.published`로 바꿔 새 `Event`를 만들어 기록한다.
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from auth.schemas import CurrentUser
from authz.core import Resource
from authz.guard import require
from authz.ports import MembershipGateway
from common.events import Event, record_event
from pins import api as pins_api
from pins.models import Pin as PinRow
from recommend import core, service


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

    event = None
    if mutation.event is not None:
        # type만 pin.published로 교정 — payload/channel/map_id는 pins.api가 이미 만든 값 그대로.
        event = Event(
            map_id=mutation.event.map_id, channel=mutation.event.channel,
            type="pin.published", payload=mutation.event.payload,
        )
    record_event(db, event)  # 7) event_log — mutation과 같은 db 세션, 커밋 전
    return mutation.pin  # 8) get_db가 커밋
