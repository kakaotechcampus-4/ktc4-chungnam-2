# backend/maps → 루트 보고 (#369 2단계 auth 세션이 maps 파일을 고친 내역, 2026-10-07)

auth 세션이 아래 2절의 "탈퇴 위임에는 이벤트를 내지 않는다"를 루트 결정(007fc55)대로 바꿨다.
- `maps/service.py::transfer_or_delete_owned_maps`: 위임한 지도마다 `record_event(db, core.member_left_event(map_id, user_id, successor))`
  한 줄 추가(`user_id`=탈퇴자, `new_owner_user_id`=후임). 넘길 사람이 없어 삭제하는 지도는 지금처럼 `map.deleted`만 나간다. docstring 갱신.
- `maps/api.py::transfer_or_delete_owned_maps`: docstring만 갱신.
- `maps/tests/test_delete_leave_api.py::test_withdrawing_owner_hands_over_or_deletes`: 위임한 지도에 `member.left` 하나(페이로드 확인)와
  `map.deleted` 없음, 삭제한 지도에 `member.left` 없음을 추가로 확인한다.
- 탈퇴자의 반응·근거 줄은 탈퇴 경로(`withdraw_user`)가 전 지도에서 지우므로, 이 이벤트는 나가기와 달리 멤버십 행을 지우지 않는다(#245).

---

# backend/maps → 루트 보고 (#369 2단계 maps 몫 — 지도 삭제·나가기·방장 위임)

브랜치 `docs/map-delete-leave-369`. 마이그레이션 `0021_maps_delete_leave`(`maps.deleted_at`,
`uq_memberships_one_owner_per_map` = `memberships(map_id) WHERE role='owner'`, 로컬 DB에서 `upgrade → downgrade -1 → upgrade` 확인).
내 지도 10개 상한(62ccd92)도 같이 했다(5절). maps 테스트 104개(이번에 늘어난 것 20개, 기존 84개), `integration` 103 passed. 백엔드 전체 실패 6개는 전부 재시도 상한 테스트로 루트의 로컬 시연용
`ATTEMPT_LIMIT=100` 때문이다(깨끗한 브랜치 head에서는 recommend 206 passed). 로컬 `.env`가 `PLACES_MODE=real`·`LLM_MODE=real`이면
integration 9개가 브랜치 head에서도 실패해서, `PLACES_MODE=dev LLM_MODE=dev`로 돌렸다.

## 1. 다른 모듈 파일을 고친 내역 (모두 추가만, 기존 함수는 그대로)
- `authz/policy.py`: `map.leave`(member), `map.delete`(owner), `ACTION_RESOURCE_TYPES`에 둘 다 `map`. 라우터가
  `require_on_map("map.delete"/"map.leave")`를 쓰려면 필요했다. `test_policy_drift` 3개가 이걸로 통과한다.
- `authz/schemas.py`: `Permissions.can_leave`.
- `common/errors.py`: `OWNER_CANNOT_LEAVE`(409), `MAP_LIMIT`(409). `test_catalog_matches_docs`가 통과한다.
- `pins/api.py`: `delete_reactions_by_user_in_map(db, *, user_id, map_id)` 추가.
- `recommend/api.py`, `recommend/service.py`: `delete_evidence_lines_by_author_in_map(db, *, user_id, map_id)` 추가. run과 후보는 건드리지 않는다.
- `integration/test_response_contract.py`: `test_map_leave_and_delete_match_the_openapi_spec`(204·403·409·404). `test_spec_route_coverage.py`의 `KNOWN_MISSING` 두 줄 삭제.

## 2. 설계와 다르게 하거나 남겨 둔 것
- **Map의 permissions는 authz가 아니라 `maps/core.py::map_permissions`가 만든다.** 역할 부분은 `authz.can`(`map.delete`, `map.leave`)에 묻고,
  넘길 사람이 있는지(지도 상태)는 maps가 판정한다. `authz.core.permissions_for`에 map 빌더를 넣으려면 `Resource`에 후임 유무를 실어야 해서 그대로 두었다.
  authz 세션이 `permissions_for`로 옮길지 정하면 된다.
- **`DbMembershipGateway.is_member`는 없다.** 설계 문서는 `is_member`·`get_role`을 말하지만 `get_role` 하나만 있어서(`pins/ports.py`도 없다) 그쪽에만 삭제 필터를 넣었다.
  새 메서드는 `current_member_ids(map_id) -> set[str]`(탈퇴자 행 포함, 삭제된 지도는 빈 집합). pins가 작성자 표시에 쓰려면 `pins/ports.py`(또는 해당 Protocol)에 이 시그니처를 추가한다.
- **탈퇴 위임에는 이벤트를 내지 않는다.** `docs/events.md`에 방장 변경 이벤트가 없다. 넘길 사람이 없어 지도를 삭제하는 경우만 `map.deleted`가 나간다.
  연결된 FE의 구성원 목록 role은 다시 불러올 때까지 옛 값이다. 필요하면 이벤트를 정해 달라.
- `next_owner`는 후임의 users 행이 없으면(이름을 못 구하면) 생략한다. 이름을 지어내지 않는다.
- 지도 삭제는 잠금 뒤에 방장 여부를 다시 확인하지 않는다(가드가 이미 봤다). 나가기는 잠근 뒤 멤버십을 다시 읽고, 그사이 나갔으면 404다.
- 초대 수락은 maps 행을 잠그지 않는다. 삭제와 동시에 수락되면 삭제된 지도에 멤버십이 하나 더 생길 수 있지만 보이지 않는다.

## 3. 확인이 필요한 것
- **인덱스 생성 전 데이터**: 로컬 dev DB(`0020`)에 방장 2명 지도 0개. 마이그레이션은 있으면 지도 id를 담아 실패한다(자동으로 고치지 않는다). 공유 DB는 확인하지 못했다.
- **auth**: `auth/service.py::withdraw_user`에서 `maps.api.transfer_or_delete_owned_maps(db, user_id)`를 불러야 한다(아직 안 부른다). 탈퇴자 멤버십 행은 지우지 않고 member로 강등만 한다.
- **pins**: `created_by_display_name` 판정(탈퇴 먼저, 그다음 `current_member_ids`)은 아직 없다.
- **realtime**: 삭제된 지도는 게이트웨이가 404를 주므로 새 SSE 구독은 막힌다. 이미 연결된 구독자에게 `map.deleted`를 보낸 뒤 닫는 순서는 realtime 몫이다.
- **동시성**: 두 세션이 동시에 나가는 테스트는 만들지 않았다. `SELECT ... FOR UPDATE`로 잠그고, 잠근 뒤 멤버십을 다시 읽는 순서만 코드로 보장한다.
  방장 2명은 부분 유니크 인덱스가 막는다(`test_two_owners_on_one_map_is_impossible`).

## 5. 내 지도 10개 상한 (62ccd92)
- 상한은 `maps/core.py::MAP_LIMIT = 10` 한 곳이고, 판정은 `core.check_map_limit(count)`가 한다(`AppError("MAP_LIMIT", detail={"limit", "count"})`).
- 세는 기준은 `service._my_map_count`다. `list_maps`와 같이 내 멤버십이 있고 삭제되지 않은 지도를 센다. 나간 지도는 행이 없어 자연히 빠진다.
- `create_map`은 입력을 검증한 뒤 센다(입력이 잘못됐으면 422가 409보다 먼저다). `accept_invite`는 토큰 확인(404/410) → 이미 구성원인지 → 아니면 상한 순서로 본다. 재수락은 막지 않는다.
- 한 사용자가 수락 두 건을 동시에 보내면 10개를 넘을 수 있다. 사용자 단위 잠금이 없어서다. 화면 흐름상 일어나기 어려워 막지 않았다.

## 4. 복잡도
예상 4(이슈 전체). maps 몫 실제 3.

---

# backend/maps → 루트 보고 (#137 — memberships.user_id 인덱스)

`ix_memberships_user_id` 추가 완료(`alembic/versions/0012_memberships_user_id_index.py`).
`uq_memberships_map_user`는 그대로 — 순수 추가만. `upgrade→downgrade -1→upgrade` 확인,
`\d memberships`로 두 인덱스 공존 확인. 별도 회귀 테스트는 추가하지 않았다 — 인덱스
자체는 쿼리 결과를 바꾸지 않아(성능만 바꿈) 단위 테스트로 관측할 게 없고, 실제 planner가
타는지는 자동 테스트보다 `EXPLAIN`으로 수동 확인하는 게 맞는 성격이라 판단했다. 전체 회귀
540 passed, 1 skipped(무관), 0 failed(변화 없음 — 예상대로 순수 인덱스 추가).

---

# backend/maps → 루트 보고 (#135 — GET /maps, 지도 생성 region)

`GET /maps`(내 지도 목록), 지도 생성 `region`(선택) 구현 완료(docs/CHANGELOG-api.md 2026-09-28,
#22·#24). `alembic/versions/0011_maps_region.py`(`maps.region_label`/`region_center` +
`ck_maps_region_both_or_neither` CHECK) 추가, `upgrade head → downgrade -1 → upgrade head`
사이클 확인. 신규 테스트 21개 + 전체 회귀 540 passed, 1 skipped(무관), 0 failed.

## 12. `confirmed_count`는 `GET /maps` 목록에서 여전히 N+1이다 — member_count와 다른 처리

이번 이슈는 `member_count`만 "N+1 안 나게" 명시했다. `member_count`는 `_member_counts()`로
목록에 나온 map_id 전체를 한 번의 `GROUP BY`로 집계해서 해결했다(`maps/service.py::list_maps`).
`confirmed_count`는 그대로 `shortlist_api.count_confirmed(db, map_id=...)`를 지도마다
호출한다 — `shortlist/api.py`가 배치 버전(`count_confirmed_many(db, map_ids)`류)을 노출하지
않고, 그 파일은 이 모듈이 아니라 shortlist 담당 세션이 소유한다(항목 5의 `count_confirmed`도
루트가 신설했다는 선례를 따름). 사용자가 보통 속한 지도 수가 적어 실질 영향은 작지만, 필요하면
`shortlist/api.py`에 배치 함수 추가를 요청한다.

## 13. `region` 필드가 이제 DB에 실제로 저장·반환된다

`docs/api-spec.yaml`의 `MapRegion{label,lat,lng}`을 `MapCreateRequest.region`·`Map.region`에
그대로 연결했다. `region_center`는 `geography(Point,4326)`로 저장하고(`pins.geom`과 동일
패턴), 응답 조립 시 `ST_X`/`ST_Y`로 되짚는다(`maps/service.py::_region_lat_lng_columns`,
`pins/service.py::_lat_lng_columns`와 동일 기법). region 없이 만드는 기존 동작은 회귀 없음
(`test_create_map_without_region_omits_region_key`로 고정).

---

# backend/maps → 루트 보고 (이슈 #4 지도 생성 파트 / 모듈 이슈 #19)

`POST /maps`, `GET /maps/{mapId}`, `POST /maps/{mapId}/invite`, `POST /invites/{token}/accept`,
`GET /maps/{mapId}/members` 구현 완료. 테스트 43개(신규) + 전체 회귀 345 passed, 1 skipped(무관),
0 failed. `alembic upgrade head` → `downgrade -1` → `upgrade head` 사이클 확인.

## 1. [최우선] `authz/deps.py` 멤버십 게이트웨이 교체가 아직 안 됐다 — 지금 로그인한 누구나 모든 지도를 본다

`maps/api.py::DbMembershipGateway`를 만들었지만 `authz/deps.py`는 건드리지 않았다(다른 세션
디렉토리). 실제로 확인함 — 지금 `uvicorn`으로 뜬 서버는 여전히 `AllowAllMembership` dev
스텁을 쓴다:
```
[pingo]   authz.MembershipGateway      dev   authz.deps._dev_membership  <-- DEV STUB
```
`user_1`이 만든 지도를 구성원이 아닌 `user_3`이 `GET /maps/{id}`로 열면 **지금은 200이 나온다**
(직접 재현 확인). `maps` 자신의 pytest 스위트는 `dependency_overrides`로 진짜 게이트웨이를
꽂아서 검증하므로 43개 테스트는 전부 통과하지만, **테스트 통과와 실제 서버 동작이 다르다** —
이 diff를 적용해야 실제로 막힌다.

적용할 diff (`authz/deps.py`):
```python
from fastapi import Depends
from maps.api import DbMembershipGateway
from maps.deps import get_db_session

def _real_membership(db: Session = Depends(get_db_session)) -> MembershipGateway:
    return DbMembershipGateway(db)

get_membership_gateway = select(
    "authz.MembershipGateway", settings.membership_mode,
    {"dev": _dev_membership, "real": _real_membership}, None,
)
```
그리고 `.env`(`.env.example` 포함)에 `MEMBERSHIP_MODE=real`. 호출부는 전부
`Depends(get_membership_gateway)`만 쓰므로 변경 없음, `common/tests/test_adapter_assembly.py`의
`MISSING_REAL`은 포트 *이름*만 비교해서 그대로 통과한다 — 주석(`"maps #19"`)만 낡는다.

## 2. seeding 훅 — 만들지 않았다(모순 발견, 사용자 확인 후 보류)

`maps/CLAUDE.md` 완료 정의는 지도 생성 시 프리시딩 잡 큐잉을 요구하는데, `architecture.md:142`는
그 잡의 지역을 "첫 핀 좌표로 확정"한다고 정의한다. `POST /maps` 바디는 `{title,start_date,end_date}`
뿐이고(#22로 `region_hint` 폐기) 이 시점 핀은 0개 — **region을 채울 방법이 없다.** 로그만
찍는 no-op 훅은 완료 정의 체크박스만 채우는 가짜 구현이라 만들지 않았다. 선택지: (a) 트리거를
"첫 핀 생성 시"(pins)로 이동 (b) `seeding_jobs.region_geom`을 nullable/pending으로. 결정 요청.

## 3. `maps/CLAUDE.md`가 낡았다

"넘지 말 것"의 `region_hint`·구성원 색 2항목은 #22·#26으로 이미 결정 완료(`docs/data-model.md`
반영됨). 루트 CLAUDE.md 4행("docs/가 최신")에 따라 이번 구현은 `docs/`를 따랐다. 문서 갱신 요청.

## 4. `invite.create` 액션이 `docs/permissions.md`에 없다

`POST /maps/{mapId}/invite`는 `require_map_member()`로 열었다 — **구성원 누구나 초대 링크를
발급**할 수 있다. owner 전용이어야 한다면 `permissions.md`에 액션을 추가해달라(`authz/policy.py`는
루트만 고친다 — `test_policy_drift.py`가 대조한다). 문서화되면 라우터는
`require_on_map("invite.create")` 한 줄 교체로 끝난다. `map.settings.edit`을 빌려 쓰는 안은
기각했다 — 무관한 액션 이름 뒤에 정책 결정을 숨기게 된다.

## 5. 생략한 필드 3개와 필요한 함수 시그니처 — 2/3 해결됨(루트, 2026-09-23)

계약(`Map`/`Member`)엔 있지만 이 모듈이 못 채우는 값은 0/false/user_id로 채우지 않고
**응답에서 생략**했다(`response_model_exclude_none=True`) — 이 방식 자체는 진행 전 사용자
확인을 받았다.
- `Map.confirmed_count` ← **해결**. `shortlist/api.py::count_confirmed(db, *, map_id)` 신설,
  `maps/service.py::_map_response`가 호출.
- `Member.display_name` ← **해결**. `auth/api.py::display_names(db, user_ids)` 신설(배치),
  `maps/service.py::list_members`·`accept_invite`가 호출.
- `Member.online` ← 아직 미해결. `realtime/api.py::online_user_ids(map_id) -> frozenset[str]`
  필요. 같은 갭이 `member.presence` 이벤트, #32 "N=온라인 구성원 수"(이 정의는 이미 "현재
  참여 중인 인원 수"로 확정돼 online과 무관해졌다)에도 걸린다.

## 6. 초대 링크 URL — 해결됨(루트, 2026-09-23)

`common/settings.py`에 `frontend_base_url` 신설(auth의 로그인 리다이렉트 갭과 같은 원인이라
하나로 합침). `maps/router.py::post_invite`가 이제 `settings.frontend_base_url`을 우선
쓴다(없으면 예전처럼 `request.base_url`로 폴백). 단, 이 링크가 실제로 열리려면 프론트에
`/invites/{token}` 경로의 "초대 수락 화면"이 있어야 한다 — 그건 여전히 `#4`의 잔여 프론트
항목이다(재오픈함).

## 7. api-spec 갭 — 비구성원 404가 스펙에 없다

`/maps/*` 4개 엔드포인트에 404가 선언돼 있지 않은데(`docs/api-spec.yaml`) `permissions.md`는
비구성원 404를 강제한다. 스펙 보강 필요.

## 8. 목서버 불일치

`contracts/mocks/handlers/maps.ts`가 카탈로그에 없는 `MAP_NOT_FOUND`를 쓴다(백엔드는
`NOT_FOUND`). 목서버의 초대 URL도 `pingo.example.com`(가짜 도메인)이다.

## 9. 정본 없는 값 2개

초대 TTL 7일(목서버 값을 그대로 따름 — `maps/core.py::INVITE_TTL`), `used_count` 증가 기준
("실제 가입 시에만"으로 정함 — `max_uses` 컬럼이 없어 아무도 강제하지 않는 순수 통계).

## 10. `maps.member_count_expected` — 고아 컬럼

API 대응 필드가 없다(`MapCreateRequest`·`Map` 어디에도 없음). `data-model.md`가 선언한
컬럼이라 스키마는 맞췄지만 이 모듈은 항상 NULL로 둔다. #32 확정 대기.

## 11. FK 후속 리비전

`pins.map_id`·`shortlist_items.map_id`에 `maps(id)` FK 추가는 이번 리비전 범위 밖이다.
기존 dev/`pingo_test` 데이터에 `"map_1"` 같은 값이 있으면 FK 위반이 나므로, truncate 또는
백필 결정이 먼저 필요하다.

---

## 만들지 않은 파일

`maps/loaders.py`(5개 라우트 전부 `require_map_member()`만 씀 — `require(action, loader)` 호출부
없어 죽은 코드), `maps/flows.py`(`architecture.md` §1.1이 초대 수락을 flow 불필요로 명시),
`maps/ports.py`(구현체·호출부 없는 Protocol은 만들지 않음 — 위 5번 항목의 `int | None` 파라미터로
같은 확장성을 얻는다). `shortlist/api.py`·`auth/api.py`·`realtime/api.py`·`seeding/api.py`도
새로 만들지 않았다 — 다른 담당 세션 디렉토리라 결정 요청 후 후속 PR로 남긴다.

## 참고 — 이번 PR의 외부 검증

계획 단계에서 DeepSeek 검수를 시도했으나 API가 연결되지 않아(연결 타임아웃, 2회 재시도) 사용자
지시에 따라 Antigravity(로컬 `agy` CLI)로 대체 검수를 받았다. Antigravity가 지적한 6개 중
실질적 결함으로 확인된 것: (a) 초대 URL이 실제로는 깨진 링크(위 6번), (b) 수동 검증
시나리오가 authz 배선 전제와 모순(위 1번 — 실제로 재현해 확인), (c) `test_constraints.py`가
마이그레이션 파일 자체의 드리프트는 잡지 못한다는 설명 정확도 문제(테스트 자체는 유효, 문서화만
수정). 필드 생략(위 5번)과 seeding 미호출(위 2번)은 이미 사용자 확인을 거친 설계라 유지했다.

---

## #159 — GET /invites/{token} 초대 요약 (2026-09-30)

**구현**: `GET /invites/{token}` → `InviteSummary`, 로그인 불요. 라우터 단위 `dependencies`는 라우트
개별로 뺄 수 없어서 인증 없는 `public_router`를 따로 두고 `main.py`에 include 한 줄을 더했다(auth의
`auth_public_router`와 같은 패턴). 다른 maps 라우트는 인증 유지(`GET /maps` 401 테스트로 고정).
`accept`도 없는 토큰 404 `INVITE_NOT_FOUND`, 만료 410 `INVITE_EXPIRED`로 바꿨다(기존엔 둘 다 401
UNAUTHORIZED였다 — 스펙이 갈랐다). 조회·수락이 `_acceptable_invite_or_raise` 하나를 공유한다.

**루트 확인 요청 (스펙 vs 구현 차이)**
1. **탈퇴한 초대자 표시 미완**: 스펙은 "탈퇴했으면 '탈퇴한 구성원'"인데, `auth.api.display_names`는
   soft delete(`deleted_at`)된 사용자의 이름도 그대로 돌려준다(의도된 동작, 과거 핀 작성자 표시용).
   그래서 지금은 **users 행 자체가 없을 때만** '탈퇴한 구성원'으로 채우고, 탈퇴(soft delete)한
   초대자는 실명이 그대로 나간다. 맞추려면 auth 쪽에 예: `auth.api.withdrawn_ids(db, user_ids) -> set[str]`
   (또는 `display_names(..., mask_withdrawn=True)`)이 필요하다 — auth 담당에게 요청 바람. 남의 모듈이라 직접 안 만들었다.
2. **rate limit 없음**: 비로그인 엔드포인트라 토큰 추측 시도를 막는 장치가 없다. 토큰이 256비트라
   추측은 비현실적이지만 v1 범위 밖이면 후속 이슈로 분리할 것(이슈 본문 요청대로 PR에도 적는다).
3. 스펙·`docs/CHANGELOG-api.md`는 이미 반영돼 있어 손대지 않았다.

**테스트**: 비로그인 200(map_id 미노출)·조회가 가입/used_count를 바꾸지 않음·404·410·초대자 행 없음
fallback·타 라우트 인증 유지. `KNOWN_MISSING`에서 `("get", "/invites/{}")` 제거. backend 전체 pytest 620 passed.
복잡도 예상 2 / 실제 2.

---

## #244(maps 몫)·#245 — 입력 길이 제한, 탈퇴자 구성원 수 (2026-10-02)

- **#244 maps**: `MapCreateRequest.title`·`MapRegion.label` `Field(max_length=100)`. 빈 제목은 기존대로 422. recommend 쪽 두 본문 선택화는 이 PR 범위 밖(recommend 담당) — 루트 xfail 2건(`regions_confirm`·`evidence_patch`)은 남겨 뒀다.
- **#245**: `Map.member_count`(단건·`GET /maps` 목록)와 `maps.api.count_members`(준비 판정 N)가 탈퇴자를 뺀다. 구성원 목록(`GET /members`)은 핀 작성자 표기용(#155)으로 그대로 둔다.
  - **다른 모듈 파일 수정 보고**: 탈퇴 여부를 알 공개 함수가 없어 `auth/api.py`에 읽기 전용 `withdrawn_user_ids(db, user_ids) -> set[str]`을 **추가**했다(기존 함수 불변). 원칙상 auth 담당에게 요청해야 하나 이슈가 "auth 탈퇴 연쇄 확인"을 명시해 최소 추가로 처리 — 마음에 안 들면 이 함수만 auth PR로 옮기면 된다.
  - **recommend 경계값(루트 확인)**: 구성원이 전부 탈퇴하면 N=0이고 `recommend.core.required_count(0)`은 0 → `ready=True`. 이슈 문구("반응 가능 인원이 없으면 준비 판정이 안 걸린다")와 다르다. 도달 경로가 "마지막 구성원 탈퇴"뿐이라(요청할 사람이 없음) 손대지 않았다. 바꾸려면 recommend 담당 몫.
