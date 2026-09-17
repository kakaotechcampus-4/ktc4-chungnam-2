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

## 5. 생략한 필드 3개와 필요한 함수 시그니처

계약(`Map`/`Member`)엔 있지만 이 모듈이 못 채우는 값은 0/false/user_id로 채우지 않고
**응답에서 생략**했다(`response_model_exclude_none=True`) — 이 방식 자체는 진행 전 사용자
확인을 받았다. FE가 이 필드들을 지금 렌더링에 쓰고 있다면(목서버 기준 개발 중이었다면) 그
화면은 이 필드들이 없는 응답에 대비해야 한다 — 필요한 함수가 준비되는 대로 각각 한 줄 교체로
채워진다.
- `Map.confirmed_count` ← `shortlist/api.py::count_confirmed(db, *, map_id: str) -> int` 필요
- `Member.display_name` ← `auth/api.py::display_names(db, user_ids: Sequence[str]) -> dict[str,str]`
  필요(배치 — `/members` N명이 N번 쿼리하지 않도록)
- `Member.online` ← `realtime/api.py::online_user_ids(map_id: str) -> frozenset[str]` 필요.
  같은 갭이 `member.presence` 이벤트, #32 "N=온라인 구성원 수"에도 걸린다 — 워크어라운드
  3개보다 이슈 1개가 맞다.

## 6. 초대 링크 URL — 지금은 브라우저로 바로 열리는 페이지가 아니다

FE 오리진의 정본이 없어(`common/settings.py`는 다른 모듈들의 어댑터 모드 전용 파일이라
이 모듈이 임의로 필드를 추가하지 않았다) `request.base_url`(백엔드 자신의 주소)로 URL을
만든다. `POST /invites/{token}/accept`는 POST 전용 API라 그 주소를 브라우저로 열면 404/405다.
FE 오리진을 어디서 관리할지(`common/settings.py`에 `INVITE_BASE_URL` 추가 등) 결정 요청 —
결정되면 `maps/router.py::post_invite`에서 `base_url` 한 줄만 바꾸면 된다.

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
