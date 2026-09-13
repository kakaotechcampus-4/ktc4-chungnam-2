# 루트 리뷰 가이드 — backend/shortlist (PR #71 멘토 리뷰 대응)

`backend/pins/for_Root.md`와 같은 형식. `shortlist/mentor-review-plan.md`는 `confirm_pin`/
`unconfirm_pin`(핀 확정/제외) 흐름만 다룬다 — 동선 계산·수동 정렬은 이 계획 범위 밖이라
아래 "이번에 하지 않은 것"에 별도로 정리했다.

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
