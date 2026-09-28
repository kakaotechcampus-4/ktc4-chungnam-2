# 루트 리뷰 가이드 — backend/shortlist (PR #71 멘토 리뷰 대응)

## [루트 검증, 2026-09-22] #103 구현 확인 + Antigravity 검수 반영

아래 "구현 범위"를 코드로 직접 확인(테스트 419 passed, alembic 단일 head 확인)했고, 5개
"확인이 필요한 것" 중 1·2·3번은 그대로 채택, 4·5번은 Antigravity 독립 검수로 실제 버그를
추가로 찾아 직접 고쳤다.

- **1번(액션 판정 없이 require_map_member만 씀)** — 채택하되, `docs/permissions.md`·
  `authz/policy.py`에 `route.recalculate`를 등록했다(maps의 `invite.create`와 같은 패턴 —
  "구성원 누구나"로 정본에 남기되, 라우터는 최소 침습으로 `require_map_member()`를 유지. 나중에
  좁힐 일이 생기면 `require_on_map("route.recalculate")`로 한 줄 교체).
- **2번(route.recalculated 페이로드가 배열)** — `docs/events.md`가 이미 그렇게 정의해뒀으므로
  그대로 채택. 문제없음.
- **3번(`sort_order` 없이 문자열 정렬)** — v1 규모에서는 그대로 채택. 다만 Antigravity가
  "POST 응답과 그 직후 GET 응답의 순서가 다를 수 있다"는 더 구체적인 문제를 찾아서(아래 참고)
  POST도 같은 정렬을 타도록 고쳤다.
- **4·5번(recommend와 클러스터링 유틸 비공유, 3km 임계값)** — 그대로 채택, 근거 타당함.

**Antigravity 독립 검수로 찾아 고친 것(직접 재현·확인 완료)**:
1. `pins.api.get_coordinates_for_pins`에 다른 모든 조회 함수와 달리 `deleted_at IS NULL`
   필터가 빠져 있었다 — 삭제된 핀이 동선에 남을 수 있었다. 필터 추가.
2. 위 필터를 추가하면 `shortlist/flows.py::recalculate_route`가 `coordinates[pin_id]`를
   무조건 인덱싱해 `KeyError`(500)가 날 수 있었다 — 좌표가 없는 pin_id는 건너뛰도록 수정.
3. `POST .../route`가 `routing.compute_routes`의 계산 순서 그대로 반환하는데, `GET`은
   `region_label` 문자열 정렬로 반환해 지역이 10개 이상이면 POST 직후 응답과 GET 응답의
   순서가 달라질 수 있었다 — POST도 저장 후 `service.list_routes`로 다시 읽어 같은 정렬로
   반환하도록 수정(SSE 이벤트 페이로드도 동일).
4. `shortlist/service.list_items`가 `added_at`만으로 정렬해, 같은 트랜잭션에서 연달아
   추가된 항목처럼 타임스탬프가 동률이면(PostgreSQL `now()`는 트랜잭션 시작 시각을 돌려줘서
   실제로 흔함) 매번 다른 순서가 나올 수 있었다 — `id`를 2차 정렬 기준으로 추가. 회귀 테스트
   추가(`test_list_items_tie_break_by_id_when_added_at_matches`), 기존
   `test_list_items_orders_by_added_at`은 added_at을 명시적으로 벌리도록 수정.
5. `shortlist/service.replace_routes`의 DELETE 후 INSERT가 동시 재계산 요청(더블 클릭 등)
   사이에 경합하면 `uq_routes_map_region` 유니크 위반(500)이 날 수 있었다 — 트랜잭션 범위
   advisory lock(`pg_advisory_xact_lock(hashtext(map_id))`)으로 같은 map_id의 재계산을
   직렬화. 커밋/롤백 시 자동 해제.

검증: `pytest -q`(backend 전체) → 419 passed, 1 skipped, 0 failed. `pytest shortlist/tests -q`
→ 55 passed. `alembic heads` → `0007_routes` 단일.

## [최신, 2026-09-22] #103 — GET/POST /maps/{mapId}/route(동선 계산) 구현

### 구현 범위

- **`shortlist/routing.py` (신규)** — 기능형 코어. `_cluster_points`(거리 임계값 기반
  union-find 단일 연결 클러스터링) + `_build_single_route`(common/geo.py의
  `nearest_neighbor_order`·`haversine_distance_m`·`approx_walk_minutes`로 구간 조립) +
  `compute_routes`(둘을 합쳐 지역별 `Route` 목록 생성, "구역 1"부터 번호 매김).
- **`shortlist/models.py`** — `Route` ORM 추가. `docs/data-model.md` 88-109행에 **루트가 이미
  #103 대응으로 스키마를 정의해둔 걸 발견**(처음엔 없어서 직접 추가하려다 파일이 세션 도중
  바뀐 걸 재확인 과정에서 알았다) — `computed_at`(내가 처음 쓰려던 `created_at`이 아니다),
  `unique(map_id, region_label)`을 그 정의 그대로 반영했다. `sort_order` 같은 추가 컬럼은
  넣지 않았다(아래 "확인이 필요한 것" 3번 참고).
- **`shortlist/schemas.py`** — `RouteLeg`, `Route`(api-spec.yaml Route와 1:1).
- **`shortlist/service.py`** — `replace_routes`(map_id 기존 행 삭제 후 재삽입, 부분 갱신 없음),
  `list_routes`(`region_label` 오름차순).
- **`shortlist/core.py`** — `to_route_response`(jsonb legs → RouteLeg 역직렬화),
  `route_recalculated_event`(payload가 다른 이벤트와 달리 dict가 아니라 `Route[]` 그대로 —
  아래 "확인이 필요한 것" 2번 참고).
- **`shortlist/flows.py`** — `recalculate_route`: `service.list_items`(added_at 순)로 확정
  리스트를 읽고, `pins.api.get_coordinates_for_pins`(신규, 아래)로 좌표만 벌크 조회 →
  `routing.compute_routes` → `service.replace_routes` → `route_recalculated_event` 발행.
- **`shortlist/router.py`** — `GET/POST /maps/{mapId}/route` 추가. 둘 다 `require_map_member()`
  만 쓴다(액션 판정 없음) — 아래 "확인이 필요한 것" 1번 참고.
- **`pins/api.py`에 함수 추가** — `get_coordinates_for_pins(db, pin_ids) -> {pin_id: (lat,lng)}`.
  shortlist가 pins 테이블을 직접 쿼리하지 않고 좌표 벌크 조회를 해야 해서 추가했다
  (`get_pin_response_for_viewer`를 추가했던 것과 같은 이유·같은 패턴, PR #80 for_Root.md 참고).
  가시성 판정은 하지 않는다 — 호출자(shortlist)가 이미 확정된(=가드레일 1로 항상 public인)
  핀 id만 넘긴다는 전제.
- **`alembic/versions/0007_routes.py` (신규)** — `docs/data-model.md`가 정의한 스키마 그대로
  `routes` 테이블 생성. `alembic upgrade head` 실제 적용 확인.
- **`shortlist/CLAUDE.md`** — "넘지 말 것"의 클러스터링 상의 요청을 이슈 #103의 위임으로
  해소된 것으로 정정, `visit_order` "결정 이슈 미결" 서술도 이미 낡은 것으로 정정
  (`docs/data-model.md`엔 이미 허용 확정으로 나와 있었다 — 지난 #88 보고서에 남겨뒀던
  지적을 이번에 실제로 고쳤다).
- **테스트**: `shortlist/tests/test_routing.py`(신규, 순수 함수 6개), `test_service.py`에
  `replace_routes`/`list_routes` 4개, `test_core.py`에 route 헬퍼 2개, `test_route_api.py`
  (신규, API 통합 13개) — 총 **shortlist/tests 54 passed**(기존 29 + 신규 25).

**검증**: `cd backend && ./.venv/Scripts/python.exe -m pytest shortlist/tests -q` → **54
passed**. `pytest authz/tests shortlist/tests pins/tests -q` → **204 passed, 1 skipped**.
`backend/`에서 인자 없이 `pytest -q` → **418 passed, 1 skipped, 0 failed**(회귀 없음).
`alembic upgrade head` 실제 적용 확인.

### 확인이 필요한 것 (판단이 들어간 곳)

1. **`GET/POST /maps/{mapId}/route`에 별도 authz 액션을 추가하지 않고 `require_map_member()`
   (순수 멤버십 게이트)만 썼다.** `docs/permissions.md`의 `member.actions`에도, 15-1
   매핑표에도 동선 계산 전용 액션이 없고, `authz/policy.py` 자신의 docstring이 "값을 바꾸는
   곳이 아니다 — 루트가 먼저 `docs/permissions.md`를 고친다"고 명시해 이 커밋에서 새 액션을
   만들지 않았다. `Route` 응답에도 `permissions` 필드가 없어(api-spec.yaml) 표시할 값 자체가
   없다. **다른 접근도 가능하다** — 예: "동선 재계산은 owner만" 같은 제약을 원하면
   `docs/permissions.md`에 `route.recalculate` 같은 액션을 추가하고 `authz/policy.py`에 반영한
   뒤 `require_on_map(action)`으로 바꾸면 된다(구조상 한 줄 교체). 지금은 "구성원 누구나"로
   구현했다 — 15-1/기획안에 반대되는 서술을 찾지 못했다.
2. **`common.events.Event.payload`는 `dict`로 타입힌트돼 있는데, `route.recalculated`
   이벤트만 `Route[]`(리스트)를 그대로 담는다.** `docs/events.md` 30행이 이 이벤트의 data를
   명시적으로 배열로 정의해서(다른 이벤트는 전부 객체) 그대로 따랐다. `Event`가
   `@dataclass`라 런타임 타입 강제가 없어 실제로는 문제없이 동작하고 테스트로도 확인했지만
   (`test_route_recalculated_event_payload_is_a_bare_list_not_wrapped`), `common/events.py`는
   여러 모듈이 공유하는 파일이라 타입힌트를 `dict | list`로 넓히는 건 이 커밋에서 직접 고치지
   않았다 — 필요하면 루트가 처리하거나 지시해달라.
3. **`routes` 테이블에 `sort_order` 컬럼을 넣지 않고 `region_label` 문자열 정렬로 GET 순서를
   고정했다.** 처음엔 안정적인 순서 보장을 위해 `sort_order` 정수 컬럼을 추가하려 했으나,
   `docs/data-model.md`가 이미 정의해둔 스키마(88-109행)에 없는 컬럼이라 정본을 그대로
   따랐다. 부작용: 지역이 10개 이상이면 `"구역 10"`이 문자열 정렬상 `"구역 2"`보다 앞에
   온다(사전식 정렬 함정). v1 실사용 규모에서 지역이 10개를 넘을 일은 거의 없다고 보고
   넘어갔다 — 실제로 문제가 되면 `region_label`을 `"구역 01"`처럼 0패딩하거나 정본에
   `sort_order`를 추가하는 두 방법 중 루트가 정하면 된다.
4. **거리 임계값(3km, `shortlist/routing.py::DEFAULT_CLUSTER_THRESHOLD_M`) 은 이슈 #103이
   위임한 대로 구현하면서 정했다.** 근거: `common/geo.py`의 도보 속도 상수(80m/분) 기준 약
   37분 거리 — 하루 일정 안에서 걸어서 묶을 만한 상한으로 잡은 v1 잠정치다.
   `shortlist/CLAUDE.md` 완료 정의의 "8km 이상 떨어진 두 클러스터" 테스트 기준보다 충분히
   작아 그 케이스는 항상 분리된다. 클러스터링 방식은 단일 연결(single-linkage, union-find) —
   A-B·B-C가 각각 임계값 이내면 A-C가 임계값을 넘어도 한 클러스터로 묶이는 체이닝이 있다는
   점은 알고 있고 의도한 단순화다(실사용 데이터로 조정 필요하면 상수 하나만 바꾸면 됨).
5. **recommend와의 클러스터링 유틸 공유는 하지 않기로 했다** — `shortlist/CLAUDE.md` "넘지
   말 것"에 원래 있던 요구사항인데, recommend에 아직 그런 유틸이 없고(코드베이스 확인 완료),
   두 문제(반경 원 교집합/합집합 vs. 확정 핀 지리적 근접도)가 다르다고 판단해 자체 구현했다.
   이슈 #103 본문이 "지역 클러스터링 기준은 구현하면서 정하되 근거를 남겨달라"고 명시적으로
   위임했다고 해석했다 — 해석이 맞는지 확인 부탁.

## [최신, 2026-09-15] #88 — app_client에 FakeMembership 기본 오버라이드 추가

배경: `authz/for_Root.md`의 "[루트 정정] ... 이슈 #87/#88/#89로 대체" 절 — `.env`의
`MEMBERSHIP_MODE=real`로 `authz.deps.get_membership_gateway`가 `DbMembershipGateway`(실제
`memberships` 테이블 조회)를 돌려주게 되면서, `shortlist/tests/test_shortlist_api.py`가 지금까지
`AllowAllMembership` dev 스텁(항상 `"member"`)에 암묵적으로 기대 통과해온 게 드러났다. 실제
`memberships` 행을 픽스처가 미리 넣는 방식은 안 된다 — 그 어댑터가 쓰는 DB 세션이 이 conftest의
테스트 트랜잭션이 아니라 별도 커넥션(`common.database.engine`, 실제 dev DB)이라 넣은 행이
안 보이고, 이 conftest는 `maps.models`를 import하지 않아 테스트 DB에 `memberships` 테이블
자체도 없다(#89에서 `maps/tests`가 이미 같은 원리로 게이트웨이 자체를 오버라이드해 43개 전부
통과 중임을 확인).

**변경**: `shortlist/tests/conftest.py`의 `app_client` 픽스처에 한 줄 추가 —
```python
app.dependency_overrides[get_membership_gateway] = lambda: FakeMembership(
    {("map_1", "user_1"): "member", ("map_1", "user_2"): "member"}
)
```
(`authz.deps.get_membership_gateway`·`authz.testing.FakeMembership` import 추가.) 이 파일이
실제로 멤버십 판정을 타는 `(map_id, user_id)` 조합은 이 둘뿐이다 — `test_confirm_pin_twice_
is_idempotent_no_duplicate_event`가 두 번째 요청에 `user_2`를 쓰는 것 말고는 전부 `map_1`/
`user_1`.

**map_2(교차-지도 테스트)는 넣지 않았다 — 코드를 직접 추적해 확인함.**
`test_confirm_pin_cross_map_pin_id_is_404_not_500`은 경로 `mapId=map_1`, 바디 `pin_id`는
`map_2` 소속 핀을 가리킨다. `shortlist/loaders.py::load_pin_for_confirm`이 `pin_row.map_id
!= mapId`를 **게이트웨이를 부르기 전에** 직접 비교해 `AppError("NOT_FOUND")`를 던진다(Rule
B는 loader 단계에서 끝남, `authz.guard.require_with_principal`의 `resolve_principal`은 그
뒤에 실행되므로 이 경로에선 아예 호출되지 않는다). 그래서 `map_2`가 딕셔너리에 없어도, 있어도
이 테스트 결과는 바뀌지 않는다 — 의도적으로 뺐다. 비구성원 케이스(`test_confirm_pin_non_
member_is_404` 등 기존 `_deny_membership` 오버라이드 3개)는 그대로 뒀다(테스트 안에서
`app.dependency_overrides[get_membership_gateway]`를 직접 덮어썼다가 되돌리는 기존 패턴,
conftest 기본값과 무관하게 동작).

**검증**: `cd backend && ./.venv/Scripts/python.exe -m pytest shortlist/tests -q` →
**29 passed**(회귀 없음). 교차-지도 테스트만 따로 `-k cross_map -v`로도 재확인.

**루트 확인 필요 없음** — `docs/` 계약이나 다른 모듈 파일은 건드리지 않았다(`shortlist/tests/
conftest.py` 단독 변경). `#89`(authz) PR이 먼저 머지돼야 이 변경이 실제로 의미가 있다(그
전엔 `MEMBERSHIP_MODE`가 아직 `dev`라 `AllowAllMembership`이 통과시켜준다) — 머지 순서는
`authz/for_Root.md`의 "#89 ... #87·#88·maps PR 머지 선행" 그대로 따른다.


`backend/pins/for_Root.md`와 같은 형식. `shortlist/mentor-review-plan.md`는 `confirm_pin`/
`unconfirm_pin`(핀 확정/제외) 흐름만 다룬다 — 동선 계산·수동 정렬은 이 계획 범위 밖이라
아래 "이번에 하지 않은 것"에 별도로 정리했다.

## PR·머지 완료 (이번 턴)

- `/tmp/pingo_prs`(공용 git 클론, 브랜치 `feat/pr71-shortlist-confirm-pin`)에 이 문서 아래
  "구현 범위"의 변경 전부가 이미 반영돼 있었다 — `shortlist/deps.py`를 포함해 내가 만든
  파일과 바이트 단위로 동일한지 확인.
- 그 클론의 `backend/alembic/env.py`에서 `# import shortlist.models`/`# import realtime.models`
  주석 줄이 중복으로 남아있던 걸 발견해 정리(다른 세션이 만든 실제 코드 문제는 아니고, 여러
  세션 변경분을 합치는 과정에서 생긴 잔여물로 보인다).
- Docker Desktop이 내려가 있어 재기동 후 `docker-compose up -d`로 `pingo`/`pingo_test` DB 확보.
- `pytest shortlist/tests` → **29 passed**. 전체 `pytest -q` → **301 passed, 1 skipped, 0
  failed**. `alembic upgrade head` 재확인.
- PR **[#80](https://github.com/kakaotechcampus-4/ktc4-chungnam-2/pull/80)** 생성 후
  `develop`에 병합 완료(머지 커밋 `59e4d6e`).

## 구현 범위

- **`shortlist/models.py` (신규)** — `shortlist_items` 테이블(`docs/data-model.md` 58-62행).
  `unique(map_id, pin_id)`. `pin_id`는 `pins.id`에 FK(0004 마이그레이션). `visit_order`는
  컬럼만 두고 이번 커밋은 쓰지 않는다.
- **`shortlist/schemas.py`** — `ShortlistItem`(`pin: pins.schemas.Pin` 중첩,
  `permissions: authz.schemas.Permissions`), `ShortlistAddRequest`.
- **`shortlist/core.py`** — 순수 함수만: `to_shortlist_item_response`,
  `shortlist_changed_event`.
- **`shortlist/service.py`** — `shortlist_items` CRUD 셸. `add_item`은 계획이 지적한 대로
  `(row, created: bool)` 튜플을 반환한다(세이브포인트+`db.rollback()` 패턴,
  `pins.api.create_ai_pin`과 동일 — 아래 1번 참고).
- **`shortlist/loaders.py` (신규)** — `authz.guard.require_with_principal()`이 쓰는 두 로더:
  `load_pin_for_confirm`(POST — 바디의 `pin_id`를 읽어 경로 `mapId`와 대조, Rule B), 
  `load_shortlist_item`(DELETE — `itemId`로 조회, Rule A 자동 성립).
- **`shortlist/flows.py`** — `confirm_pin`/`unconfirm_pin`. 계획의 의사코드와 달리 **인가
  로직을 직접 갖지 않는다** — 아래 2번(가장 중요한 이탈)에서 이유를 설명한다.
- **`shortlist/router.py`** — `GET/POST /maps/{mapId}/shortlist`, `DELETE /shortlist/{itemId}`.
  `PUT .../order`·`GET|POST .../route`는 포함하지 않음(아래 "이번에 하지 않은 것").
- **`pins/api.py`에 함수 추가** — `get_pin_response_for_viewer(db, pin_id, viewer_id,
  principal) -> Pin`. `ShortlistItem.pin`을 조립하려면 목록 화면과 같은 모양의 완성된
  `Pin`(lat/lng·반응 집계·permissions)이 필요한데 `pins.api`엔 그런 함수가 없었다 — 아래
  4번 참고.
- **`authz/guard.py`에 함수 추가** — `require_with_principal(action, loader)`.
  `require()`는 `loaded.obj`만 반환하는데, shortlist는 응답에 permissions를 계산해 넣으려면
  `Principal`도 그대로 필요하다 — 아래 2번 참고.
- **`alembic/`** — `0004_shortlist_items.py` 신규 리비전, `alembic/env.py`에
  `import shortlist.models` 추가. `alembic upgrade head`로 실제 적용 확인.
- **`backend/main.py`** — `shortlist.router` 등록(주석 해제).
- **`backend/shortlist/CLAUDE.md`** — 계획의 "문서 모순 수정 필요" 절대로 "확정 리스트 변경
  시 동선 즉시 재계산" 서술을 삭제하고 `docs/api-spec.yaml` 기준(`POST .../route` 수동
  트리거만)으로 정정.
- **테스트**: `shortlist/tests/`(신규, `test_core.py`·`test_service.py`·
  `test_shortlist_api.py`, 29 passed) + `pins/tests/test_api.py`에
  `get_pin_response_for_viewer` 테스트 2개 + `authz/tests/test_guard.py`에
  `require_with_principal` 테스트 2개 추가.

**검증(Docker로 PostGIS 띄운 뒤 실제로 실행 확인):**
```
cd backend && python -m pytest authz/tests shortlist/tests pins/tests -q
```
→ **174 passed, 1 skipped**. 전체(`backend/`에서 `python -m pytest -q`, 인자 없이)는
**301 passed, 1 skipped, 0 failed**(처음 돌렸을 땐 `recommend/flows.py`의 기존
`resolve_principal` 직접 호출 위반 1개가 더 있었는데, 이 세션이 만든 코드는 아니고
`recommend` 세션이 그사이에 고친 것으로 보인다 — 아래 5번 참고).

**주의 — 모듈별 테스트 디렉터리를 임의 순서로 조합해 돌리면 실패할 수 있다.** 예:
`python -m pytest shortlist pins authz -q`처럼 `shortlist`가 먼저 오는 조합은
`relation "reactions" does not exist` 같은 `UndefinedTable` 오류를 낸다 — `shortlist/tests/
conftest.py`와 `pins/tests/conftest.py`가 각자 세션 스코프 `test_engine`에서 **같은 물리
DB**(`pingo_test`)에 대해 독립적으로 `Base.metadata.create_all`/`drop_all`을 실행하는데,
pytest가 한쪽 픽스처를 그 모듈의 마지막 테스트 직후 일찍 종료(finalize)시키면서 아직 안 끝난
다른 모듈의 테이블까지 같이 지워버리는 것으로 보인다. 이건 shortlist가 새로 만든 문제가
아니라 `pins/tests/conftest.py`가 이미 갖고 있던 패턴(물리 DB 하나를 여러 모듈이 각자
create_all/drop_all)이 모듈이 늘어나며 드러난 기존 설계의 취약점이다 — **위처럼 `backend/`
루트에서 인자 없이 `pytest -q`를 돌리거나(디렉터리 알파벳 순회라 각 모듈이 순서대로 끝까지
실행됨), 최소한 `authz/tests shortlist/tests pins/tests`(먼저 확인된 순서)로 돌릴 것을
권한다.** 근본 해결(예: 모듈별 conftest가 서로 다른 스키마/DB를 쓰거나, 공용 conftest로
합치기)은 여러 모듈에 걸친 테스트 하네스 변경이라 루트 확인이 필요해 보인다.

## 꼭 읽어야 할 것 (판단이 들어간 곳)

1. **`add_item`의 `db.rollback()`은 "마지막 커밋 지점"까지 되돌아간다 — 같은 트랜잭션 안에서
   먼저 flush만 하고 커밋하지 않은 다른 쓰기가 있으면 그것도 함께 사라진다.** `pins.api`가
   이미 겪은 `begin_nested()` 세션 deactive 버그(`pins/for_Root.md` 1번)와 다른, 이 패턴의
   또 다른 함정이다 — 처음엔 `shortlist/tests/test_service.py`에서 `service.add_item`을
   커밋 없이 같은 세션에서 두 번 연달아 부르는 테스트를 짰다가 `_find_existing_item`이
   `NoResultFound`를 던지는 걸 실제로 봤다(첫 번째 호출의 flush까지 롤백됨). **프로덕션
   경로는 안전하다** — `flows.confirm_pin`에서 `add_item` 앞에 다른 쓰기가 없어(읽기만),
   요청 하나에 `add_item`이 정확히 한 번만 불린다(`common.database.session_scope`가 요청당
   한 번 커밋). 테스트만 두 호출 사이에 `db_session.commit()`을 넣어 실제 요청 경계를
   흉내내도록 고쳤다. **다른 세션에 영향 가능성**: `add_item`류 패턴(세이브포인트+
   `db.rollback()`)을 같은 트랜잭션에서 두 번 이상 부르는 코드가 있다면 같은 함정이 있을 수
   있다 — 확인 필요.
2. **계획의 의사코드는 `confirm_pin`/`unconfirm_pin`이 `membership.is_member()`를 직접
   부르는 모양이었지만, 실제로는 그렇게 짜지 않았다 — `authz/tests/test_rule_a_static.py`가
   `resolve_principal`을 `authz.guard` 밖에서 부르면 실패로 잡는 정적 테스트라는 걸 뒤늦게
   발견했다.** 처음엔 계획대로 `flows.py`에서 `authz.service.resolve_principal`+
   `authz.core.can()`을 직접 불렀는데, 전체 스위트를 돌리자 이 정적 테스트가 실패했다.
   **고친 구조**: 인가를 `router.py`의 `authz.guard.require_with_principal(action, loader)`로
   옮기고, `flows.py`는 이미 검증된 `(pin_row 또는 item_row, principal)`만 받는다. POST는
   바디의 `pin_id`와 경로 `mapId`가 다를 수 있어(Rule B) `load_pin_for_confirm` 로더가 직접
   `pins.api.get_pin_for_viewer`로 핀을 읽고 대조한 뒤 `Resource`를 만든다 — `pins/loaders.py`
   와 같은 원칙. **이 과정에서 `authz.guard`에 `require_with_principal`을 새로 추가했다**
   (`require()`는 `loaded.obj`만 반환해 permissions 계산에 필요한 `Principal`을 버린다) —
   authz 모듈 파일을 shortlist 세션이 직접 건드린 것이라 별도로 표시해둔다. HTTP 응답 동작
   자체(상태 코드·본문)는 계획이 의도한 것과 동일하다 — 내부 구조만 프로젝트의 기존 Rule A
   강제 방식에 맞춘 것.
3. **가드레일 1 — 본인 소유 비공개 AI 후보를 확정 리스트로 직접 승격시킬 수 없게 막는
   체크를 계획에 없던 걸 추가했다.** `pins.api.get_pin_for_viewer`는 핀 소유자 본인의
   비공개 핀 열람은 허용한다(가시성 판정일 뿐). 그런데 `confirm_pin`이 그 핀을 그대로
   확정 리스트(항상 전체 공개)에 올리면, 「지도에 올리기」(`recommend.publish`)를 거치지
   않고 비공개 AI 후보가 전체 공개로 새는 셈이라 최종기획안 7절 가드레일 1("대안은 요청한
   사람에게만 먼저 보이고, 「지도에 올리기」로만 공개된다")을 어긴다. `load_pin_for_confirm`
   에서 `pin.visibility == "private"`이면 `AI_PIN_PRIVATE`로 막았다 —
   `test_confirm_own_private_pin_is_blocked_guardrail_1`로 회귀 고정. **이 체크가 맞는
   설계인지는 루트 확인이 필요하다** — 대안으로 "비공개 AI 후보는애초에 `can_add_to_
   shortlist`가 false로 내려가게 `authz.core._pin_permissions`에서 걸러야 한다"는 접근도
   있다(지금은 `kind != '확정'`만 본다, `resource.kind`에 visibility 정보가 없어 authz
   레이어에서는 판정이 안 됨 — 그래서 pins 레이어에서 막았다).
4. **`pins/api.py`에 `get_pin_response_for_viewer`를 새로 추가했다** — 다른 모듈 파일을
   shortlist 세션이 직접 건드린 두 번째 지점. `ShortlistItem.pin`은 `docs/api-spec.yaml`상
   완전한 `Pin`(lat/lng·reaction_summary·permissions 포함)이어야 하는데, 기존
   `pins.api.get_pin_for_viewer`는 ORM 행만 돌려준다. `pins.service`의 비공개 헬퍼
   (`_lat_lng_columns`·`_reaction_counts_for_pin`)를 같은 모듈 안에서만 재사용해 조립한다
   — pins·reactions 테이블을 shortlist가 직접 쿼리하지 않는다는 원칙은 지켰다. `pins/tests/
   test_api.py`에 테스트 2개 추가.
5. **`authz/tests/test_rule_a_static.py`가 한때 `recommend/flows.py`의 위반을 잡고 있었다**
   (전체 스위트를 처음 돌렸을 때 발견 — 이 세션이 만든 코드는 아니다). 이후 다시 돌리자
   사라졌다 — `recommend` 세션이 그사이 같은 문제를 고친 것으로 보인다. 혹시 아직 남아있는
   경우를 대비해 적어둔다: `resolve_principal`을 `recommend/flows.py`에서 직접 부르지 말고,
   위 2번에서 shortlist가 쓴 `authz.guard.require_with_principal(action, loader)` 패턴(또는
   필요 시 `require()`)로 옮겨야 정적 테스트가 통과한다.

## 이번에 하지 않은 것 — 결정/상의 필요

- **`PUT /maps/{mapId}/shortlist/order`(수동 정렬)**, **`GET|POST /maps/{mapId}/route`(동선
  계산)** — `mentor-review-plan.md`가 다루지 않는다. `shortlist/CLAUDE.md` "넘지 말 것"이
  "지역 클러스터링은 recommend의 5-6-1 로직과 같은 원칙을 공유 유틸로 뽑는 걸 루트와
  상의한다"고 명시하고 있어, 그 공유 유틸(겹치는 원 교집합/합집합 판정을 `common`이나
  별도 라이브러리로 어디에 둘지)을 루트가 정하기 전엔 착수하지 않는 게 맞다고 판단했다.
  `docs/data-model.md`의 "9/4 회의로 해결된 것"에 `visit_order` 수동 정렬은 이미 허용
  확정으로 나와 있으니(`shortlist/CLAUDE.md`의 "결정 이슈 미결" 서술은 그 점에서도 낡았다),
  최근접 이웃 계산용 공유 유틸 위치만 정해지면 바로 착수 가능.
- `visit_order` 필드는 테이블에 있지만 이번 커밋의 어떤 코드도 쓰지 않는다(위와 같은 이유).

## 환경 이슈

- 이 머신의 Python은 프로젝트 전용 가상환경이 아니라 전역 설치본(`Python310`)이라, 백엔드
  `pip install -r requirements.txt`가 다른 도구(`aider-chat`, `transformers`,
  `google-genai` 등)와 버전 충돌 경고를 냈다(`fastapi`/`pydantic`/`httpx`/`pyyaml`/
  `starlette`가 그 도구들이 원하는 최신판보다 낮은 버전으로 내려감). 백엔드 테스트 자체는
  전부 통과했지만, 이 머신에서 그 도구들도 같이 쓴다면 가상환경(`venv`) 분리를 권한다 —
  `backend/CLAUDE.md`의 로컬 실행 절엔 venv 언급이 없어 다른 세션도 같은 걸 겪을 수 있다.
- `docker-compose up -d` 실행 시 컨테이너(`backend-db-1`, `backend-redis-1`)가 이미 떠
  있었다 — 다른 세션이 먼저 띄워둔 것으로 보인다.
