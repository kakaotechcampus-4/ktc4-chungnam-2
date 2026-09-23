# 루트 리뷰 가이드 — backend/recommend

`backend/pins/for_Root.md`·`backend/authz/for_Root.md`와 같은 형식. 이 파일은 두 세션에 걸친
작업을 누적해서 담는다 — 아래 "#108" 절이 최신(코어 파이프라인 전체), 그 아래 "PR #71" 절이
`publish_candidate` 하나만 다룬 이전 세션 기록이다.

---

# #108 — 코어 파이프라인(`llm` 스텁 대상 통합)

## 구현 범위

`#108` 지시(“recommend 코어 파이프라인을 llm 스텁 대상으로 구현해달라”)를 그대로 따랐다 —
`llm.service.plan_evidence/label_place/rank_candidates` 스텁을 실제로 호출하고, places/seeding은
기다리지 않고 dev 스텁으로 그 자리를 메웠다.

- **`recommend/models.py`** — `evidence_lines`/`regions`/`exclusions` 추가. `recommend_runs`에
  `last_funnel`(JSONB, data-model.md엔 없음) 추가. `candidates.region_id`에 이제 FK를 건다
  (`regions`가 생겼으므로).
- **`recommend/constraints.py`(신규)** — `docs/constraints.md` 표 전사(authz/policy.py가
  permissions.md를 전사하는 것과 같은 원칙). 카테고리별 적용 대상 fact_key, `unknown_policy`.
- **`recommend/ports.py`/`recommend/deps.py`(신규)** — `PlaceSearchGateway`/`PlaceFactsGateway`
  두 포트 + dev 스텁(`common.adapters.select()`, `settings.places_mode` 재사용). 실제 장소
  데이터가 아니다 — 아래 "꼭 읽어야 할 것" 참고.
- **`recommend/core.py`** — 순수 함수 전부 추가: `check_readiness`/`required_count`/
  `assemble_evidence`/`circles_all_overlap`/`region_signature`/`merge_circles`/`widen_radius`/
  `is_within_any_region`/`build_check`/`apply_disqualifier_filters`/`funnel_counts`/
  `check_retry_limit`.
- **`recommend/service.py`** — recommend 소유 테이블 CRUD 전부(run/evidence/region/candidate/
  exclusion).
- **`recommend/flows.py`** — `get_readiness`/`create_run`/`list_evidence`/`patch_evidence`/
  `confirm_regions`/`execute_run`/`widen_run`/`retry_run`/`get_result` 추가(`publish_candidate`는
  그대로 유지).
- **`recommend/loaders.py`(신규)** — run 하위 엔드포인트(mapId가 URL에 없다)를 위한
  `authz.guard.require_with_principal()` 로더.
- **`recommend/router.py`(신규)** — `docs/api-spec.yaml` `recommend` 태그 엔드포인트 9개 전부.
  `main.py`의 주석 처리된 `include_router` 줄도 풀었다.
- **마이그레이션**: `alembic/versions/0008_evidence_regions_excl.py`.
- **다른 모듈에 추가한 함수(아래 "루트 확인 필요"에도 다시 정리)**:
  `pins/api.py::count_reacted_users`/`get_category_pin_coordinates`/`list_reasoned_reactions`,
  `maps/api.py::count_members`.
- **`common/tests/test_adapter_assembly.py`**: 새 포트 2개(`recommend.PlaceSearchGateway`/
  `PlaceFactsGateway`)를 `MISSING_REAL`에 등록(이 파일 자체가 "새 포트 추가 시 여기 등록"을
  전제로 설계된 회귀 테스트라 다른 모듈 파일이어도 직접 고쳤다).
- **테스트**: `test_core.py`/`test_constraints.py`/`test_service.py`/`test_flows.py`/
  `test_router.py`(신규, TestClient 골든 패스 — run 생성→evidence→지역확인→execute→result→publish).

**검증(Docker로 PostGIS 띄운 뒤)**:
```
cd backend && ./.venv/Scripts/python.exe -m pytest --ignore=.venv -q
```
→ **496 passed, 1 skipped**(전체 백엔드, 3회 반복 확인 — 안정적). `recommend/tests`만 92
passed. `ruff check`는 이 세션이 새로 쓴 파일 전부에 대해 통과 — 남은 경고 2종류
(`B008` Depends-as-default, `UP035` typing.Mapping/Sequence)는 기존 코드베이스 전체가 이미
쓰는 컨벤션과 정확히 같은 패턴임을 직접 대조 확인하고 그대로 뒀다(예: shortlist/loaders.py의
Depends 기본값, authz/policy.py·common/geo.py·llm/service.py의 typing.Mapping/Sequence).
`alembic upgrade head` 정상(0008이 head). `python -c "import main"` 정상.

## 꼭 읽어야 할 것 (v1 스텁이 만든 구조적 한계 — 실제 모델/장소 데이터가 오면 반드시 재검토)

1. **후보 풀 확보(`PlaceSearchGateway`)와 장소 원자료(`PlaceFactsGateway`) 둘 다 진짜 데이터가
   아니다.** `places`(#14)/`seeding`(#13)이 없어 `recommend/deps.py`의 dev 스텁이 이 자리를
   메운다 — `PlaceSearchGateway`는 반경 중심에서 고정 오프셋 6곳에 합성 `place_id`를 만들고,
   `PlaceFactsGateway`는 항상 빈 dict를 반환한다(그래서 라벨링은 늘 `unknown`이고
   `unknown_policy`로만 분기된다 — architecture.md 3절이 예상한 그대로 작동은 하지만, 실제
   추천 품질과는 무관하다). **`places`가 실구현되면 이 두 스텁을 교체하는 게 최우선**이다 —
   지금 상태로는 "필터 순서·이벤트·권한 배선이 도는 것"만 증명하지, 실제 추천 결과의 의미는
   없다(recommend/CLAUDE.md 우선순위 절이 원한 바로 그 순서 — 스텁으로 통합부터).
2. **반경 사유(circle_anchor_pin_id/circle_radius_m)가 v1에서는 절대 채워지지 않는다.**
   `llm.service.plan_evidence` 스텁은 `EvidenceLine(**raw_reason)`을 그대로 통과시킬 뿐 구조화를
   하지 않는다 — 자유 텍스트(반응 reason_text)에서 "해운대 기준 도보 5분" 같은 반경 사유나
   `fact_key`를 뽑아내는 건 실제 모델(#12)이 붙어야 가능하다. 그래서 `flows.create_run`은
   **모든 run에 대해 예외 없이 "기본값 원"(그 카테고리 핀들의 중심 좌표, 반경
   `DEFAULT_REGION_RADIUS_M=2000`m 고정)을 만든다** — 5-6-1 겹침 판정(`region_signature`/
   `circles_all_overlap`)과 `REGION_CONFLICT` 409 경로 자체는 구현·단위테스트로 커버했지만,
   실제 통합 경로에서는 항상 원이 0~1개라 트리거될 일이 없다(`confirm_regions`가 매번
   무충돌 200으로 끝난다). **모델이 실제로 반경 사유를 구조화하기 시작하면 이 기본값 fallback을
   "명시적 반경 사유가 하나도 없을 때만" 쓰도록 좁혀야 한다** — 지금은 유일한 경로라 항상 쓰인다.
   - **연쇄 효과 — `widen_radius`(가드레일4)**: "반경을 넓히는 것은 사람이 하고, 기본값 원만
     자동으로 넓힌다"는 원칙에서 "기본값 원 vs 사람이 명시한 원"을 구분해야 하는데, 위 이유로
     v1은 그 구분을 할 수가 없다 — 그래서 `flows.widen_run`은 **run의 원 전부를 무조건
     2배(`core.WIDEN_FACTOR`)로 넓힌다.** 모델이 붙어 명시적 원이 실제로 생기면 이 함수를
     "기본값 원만" 넓히도록 좁혀야 한다. **배율 2.0 자체도 문서에 없는 이 세션의 임의값** —
     루트가 실제 배율을 정해주면 좋겠다.
3. **`price_bucket`/`capacity_min` 실격 판정이 "표시만" 하고 절대 실패시키지 않는다.**
   `docs/constraints.md`는 이 둘을 "1인/음료/1박 상한 비교", "3인 이상 수용" 같은 **값 비교**로
   정의하는데, `docs/data-model.md`의 `evidence_lines` 스키마엔 badge/fact_key/text/circle_*뿐
   사용자가 명시한 **기준값**(가격 상한이 얼마인지, 인원이 몇 명인지)을 담을 컬럼이 없다.
   `recommend/constraints.py::VALUE_COMPARISON_UNSUPPORTED`로 이 둘을 명시적으로 격리하고
   `_passes_hard_check`가 항상 `True`를 반환하게 했다 — Check 자체(라벨·confidence)는 정직하게
   노출하지만 실격 판정에는 못 쓴다. **evidence_lines에 값 컬럼을 추가하거나 llm의 구조화
   출력에 임계값을 싣는 결정이 나야 이 둘을 실제로 실격 필터에 쓸 수 있다.**
4. **`member_fulfillment`(가드레일5 "구성원 충족 집계")가 항상 빈 `{}`다.** 3번과 같은 종류의
   갭 — "구성원 각자가 어떤 선호를 요구했고 이 후보가 그걸 몇 명분 충족하는지" 집계하려면
   구성원별 선호 요청이 구조화된 형태로 있어야 하는데, evidence_lines는 badge='preferred'
   텍스트만 있고 "누가 어떤 fact_key를 원했는지" 구조가 없다. 이것도 3번과 같은 스키마 결정이
   먼저 필요하다.
5. **인가 — `recommend.request` 액션을 run 하위 엔드포인트 전부(evidence 조회/토글·지역확인·
   실행·결과조회·반경넓히기·재시도)에 재사용했다.** `docs/permissions.md`/`authz/policy.py`가
   이 세부 액션들을 개별 선언해두지 않아서다 — `require_map_member()`/`require_on_map()`은
   `mapId`가 URL에 있는 라우트에만 쓸 수 있는데(하드코딩된 `Path(...)` 전제, `authz/guard.py`
   docstring 참고), 위 엔드포인트들은 `runId`만 있다. 그래서 `recommend/loaders.py::load_run`
   (run을 읽어 `Resource(type="map", map_id=run.map_id)`를 채우는 로더) +
   `authz.guard.require_with_principal("recommend.request", load_run)` 조합으로 "구성원이면
   전부 허용"을 구현했다 — 비구성원은 여전히 404, 구성원이면 항상 통과(세부 액션 구분 없음).
   **"누가 실행/재시도/반경넓히기를 할 수 있는가"가 "구성원 누구나"로 충분한지, 아니면
   `candidate.requested_by`처럼 author 제약이 필요한지는 루트 결정이 필요하다** — 지금은 남의
   run도 아무 구성원이나 실행/재시도할 수 있다.
6. **`patch_evidence`는 권한 없는 토글이 하나라도 섞이면 요청 전체를 403으로 거절한다**(부분
   허용/조용한 무시가 아니다) — `docs/api-spec.yaml`이 이 엔드포인트에 `Forbidden`을 명시적으로
   선언해뒀다는 점에 근거한 해석이다(`contracts/mocks`의 목 서버는 조용히 무시하지만, 그건
   403 계약이 확정되기 전에 쓰인 것으로 보인다).
7. **`regions` 테이블에 `docs/data-model.md`의 `geom geography` 컬럼을 두지 않았다.** 대신
   병합된 원을 `center_lat`/`center_lng`/`radius_m`(평범한 float/int)로 저장한다 —
   `candidates.lat/lng`(이전 세션 결정)와 같은 "차원 압축" 논리이지만, 이번엔 컬럼을 아예
   PostGIS 타입에서 float으로 바꾼 것이라 이전 결정보다 이탈 폭이 크다. **data-model.md에
   반영할지, 아니면 이후 `regions.geom`을 실제로 채우는 세션이 되돌릴지 루트 결정이 필요하다.**
8. **가드레일6 "이미 거절된 장소"의 절반만 구현했다.** `exclusions.reason='proposed'`(다시
   추천 받기 루프)는 `retry_run`이 채운다. `reason='dismissed'`(직접 찍은 핀에 🚫 반응을 남긴
   장소)는 구현하지 않았다 — pins에 "이 사용자가 어떤 place_id에 반대했는지" 조회 함수가 없다.
   **필요하면 `pins/api.py`에 함수를 하나 더 추가해야 한다(아래 "루트 확인 필요" 5번).**
9. **`run.candidates_ready`(개인 채널)만 발행한다.** `run.progress`(8단계 진행)·`run.failed`는
   구현하지 않았다 — v1은 실제 비동기 파이프라인이 없어(요청 안에서 전부 동기 처리) 여러 단계에
   걸쳐 진행률을 보고할 실질적인 지점이 없고, 실패는 `AppError`로 곧장 HTTP 에러가 되어
   `run.failed` 이벤트로 별도 알릴 상태 자체가 안 남는다.

## 루트 확인·결정 필요 (모아서)

1. **기본값 반경 원의 반경값(2000m)과 위젯 배율(2.0)** — 둘 다 이 세션이 문서 근거 없이 정한
   값이다(위 2·2번 항목).
2. **`price_bucket`/`capacity_min` 임계값을 어디에 저장할지** — `evidence_lines` 스키마 확장
   또는 llm 구조화 출력 확장(위 3·4번 항목, `member_fulfillment`도 같이 풀린다).
3. **run 하위 엔드포인트(evidence/지역확인/실행/결과/반경넓히기/재시도)의 정확한 인가 수준** —
   "구성원 누구나"로 충분한지, `candidate.requested_by`처럼 author 제약이 필요한지(위 5번).
   필요하다면 `docs/permissions.md`/`authz/policy.py`에 세분화된 액션 이름을 추가하는 게
   `recommend.request` 재사용보다 나을 수 있다.
4. **`regions.geom`(PostGIS) 컬럼을 아예 안 둔 결정**(위 7번) — data-model.md 반영 여부.
5. **가드레일6 "거절된 장소" 완성** — `pins`에 "이 사용자가 반대(🚫)한 place_id 목록" 조회
   함수가 필요하다(위 8번). `pins/api.py`가 아직 없어 이번엔 만들지 않았다 — pins 세션 몫으로
   남긴다.
6. **(이관) readiness의 N(#32) 정의** — `maps.api.count_members`로 "지도 전체 구성원 수"를
   썼다. #32 자체가 여전히 미결이라 이 값이 최종 정의가 맞는지는 그 결정이 나야 안다.
7. **`pins/api.py`·`maps/api.py`에 이번에 추가한 함수 4개**
   (`count_reacted_users`/`get_category_pin_coordinates`/`list_reasoned_reactions`/
   `count_members`) — 각 모듈 소유 파일이라 그 세션들의 리뷰가 필요하다. 전부 읽기 전용 집계
   함수이고 기존 함수(`get_coordinates_for_pins` 등)와 같은 패턴으로 맞췄다.
8. **(이관, 이전 세션이 이미 보고) `pins.api.create_ai_pin`의 이벤트 타입 버그** — 여전히
   `flows.py`에서 우회 중, pins 세션이 근본 수정할 항목.

---

# PR #71 멘토 리뷰 대응 — `publish_candidate` 슬라이스

## 구현 범위

`recommend/mentor-review-plan.md`는 이 모듈 전체가 아니라 **`flows.py::publish_candidate`
한 함수(「지도에 올리기」)만** 다루는 설계 문서였다 — 착수 조건으로 "`recommend_runs`/
`candidates` 테이블과 `recommend/service.py`·`core.py`가 최소 스켈레톤으로 존재"를 걸어뒀는데,
이 세션 시작 시점엔 그것도 없었다(`recommend/`엔 `CLAUDE.md`뿐). 그래서 그 스켈레톤부터
같이 만들었다:

- **`recommend/models.py` (신규)** — `recommend_runs`/`candidates` 두 테이블만(evidence_lines/
  regions/exclusions은 근거 조립·지역확인·재시도 세션이 추가할 몫이라 만들지 않음).
- **`alembic/versions/0003_recommend_runs_candidates.py` (신규)** + `alembic/env.py`에
  `import recommend.models` 추가.
- **`recommend/core.py` (신규)** — `check_run_ready(run)` 하나. 순수 함수.
- **`recommend/service.py` (신규)** — `load_candidate_with_run`, `link_published_pin`(가드 UPDATE).
- **`recommend/flows.py` (신규)** — `publish_candidate`. 계획 문서 그대로 구현하되 아래 "꼭
  읽어야 할 것"의 이유로 세 군데를 계획과 다르게 구현했다.
- **테스트**: `test_core.py`(순수), `test_service.py`, `test_flows.py`(계획 "검증" 절의 케이스
  전부 — 비구성원/비작성자/NOT_READY/멱등 2연속/동시 게시 레이스/PIN_DUPLICATE 롤백/
  IDEMPOTENCY_CONFLICT 롤백/멱등 경로에서 핀 소실 전파, 총 8개 시나리오 + 순수 함수 테스트).

**검증(실제로 실행 확인, Docker로 PostGIS 띄운 뒤)**:
```
cd backend && ./.venv/Scripts/python.exe -m pytest authz/tests auth/tests common/tests pins/tests recommend/tests -q
```
→ **210 passed, 1 skipped**(pins의 기존 skip). `recommend/tests`만 19 passed. `ruff check`
recommend 소스+테스트 전부 통과(마이그레이션 파일의 `Union`/`Sequence` 스타일 경고는
0001_pins.py/0002_event_log.py에도 이미 있는 기존 컨벤션이라 그대로 따름 — 새로 만든 문제
아님, 확인 완료). `python -c "import main"` 정상.

## 꼭 읽어야 할 것 (계획 문서와 실제 구현이 갈라진 곳)

1. **계획 문서가 전제한 멤버십 인터페이스가 이미 삭제된 상태였다.** `recommend/
   mentor-review-plan.md`(09-11 22:46 작성)의 `flows.py` 초안은 `membership.is_member(map_id,
   user_id) -> bool`을 썼는데, 이건 `pins/ports.py`가 갖고 있던 옛 `MembershipGateway`
   Protocol이다 — pins의 PR #71 재작업(09-12 00:10~00:24, 계획보다 늦게 끝남)이 그 파일에서
   `MembershipGateway`/`EventPublisher`를 통째로 삭제하고 `authz.guard`/`authz.core.can()`
   체계로 옮겼다(`pins/for_Root.md` 참고). 계획이 참조한 인터페이스 자체가 없어져서 그대로
   옮길 수 없었다.
2. **비구성원 실패 코드를 403 FORBIDDEN → 404 NOT_FOUND로 정정.** 계획의 실패 매핑 표는
   "요청자가 구성원 아님 → 403 FORBIDDEN"이라고 썼지만, `docs/permissions.md`("권한을
   어디서 강제하는가" 절, 계약 변경 — 이 역시 계획보다 늦게 확정)는 "비구성원 → 404(존재를
   안 흘림) / 구성원인데 액션 불가 → 403"으로 못박아뒀다. 두 코드 다 있는 게 아니라 이
   문서가 최신 정본이라고 판단해 404로 구현했다.
3. **"후보가 남의 run 소속" 케이스를 AI_PIN_PRIVATE → FORBIDDEN으로 정정(2번보다 판단이
   더 필요했던 부분).** 계획은 이 케이스에 `AI_PIN_PRIVATE`(404)를 썼다. 처음엔 "비공개
   후보니까 존재를 안 흘리는 게 맞다"고 판단해 그대로 구현했는데, **전체 테스트를 같이
   돌려보니 `authz/tests/test_rule_a_static.py::test_only_guard_module_calls_resolve_principal`
   가 실패했다** — 이 테스트는 "`resolve_principal`은 `authz.guard` 밖에서 직접 호출하지
   않는다"(Rule A)를 AST로 강제한다. `AI_PIN_PRIVATE`를 직접 만들려면 `resolve_principal`+
   `can()`을 flows.py에서 직접 불러야 하는데, 그게 Rule A 위반이었다. 그래서
   `authz.guard.require("recommend.publish", loader)`가 돌려주는 의존성 함수를 그대로
   호출하도록(라우터가 아니라 이미 읽은 candidate로 `loaded`를 직접 채워서) 바꿨고, 그
   함수는 "구성원인데 액션 불가 → 403 FORBIDDEN"만 낸다(`docs/permissions.md`의 2값
   체계와도 일치 — 이 문서엔 애초에 AI_PIN_PRIVATE 같은 세 번째 값이 없다). 계획의
   AI_PIN_PRIVATE는 Rule A 확정 전에 쓰인 추측이었다고 결론 내렸다.
   - **루트 확인 필요**: `authz.guard.require()`를 FastAPI 라우트가 아닌 평범한 함수(flows.py)에서
     `Depends` 없이 직접 호출하는 이 방식이 처음 나온 사례다(`authz.core.Resource`/`.obj`를
     흉내낸 작은 `_LoadedCandidate` dataclass로 `loaded=`를 채움). `shortlist`의 핀 확정
     플로우도 같은 모양(멘토 코멘트 1,3 — 게시/확정 둘 다 "flow 함수" 패턴)일 가능성이 커서,
     이 패턴이 맞다면 `authz.guard`에 "loader 없이 loaded를 직접 받는" 변형을 정식으로
     추가하는 게 나을 수도 있다 — 지금은 `require()`의 클로저를 그대로 재사용하는 임시방편이다.
4. **`pins.api.create_ai_pin`의 이벤트 타입 버그(pins 소관, 이 세션은 우회만 함).**
   `create_ai_pin`이 반환하는 `mutation.event`는 `pins.core.pin_created_event(pin)`이 만든
   것이라 `type="pin.created"`다. 그런데 `docs/events.md`(전체 채널 표)는 「지도에 올리기」의
   타입을 `"pin.published"`로 이미 못박아뒀고, `create_ai_pin` 자신의 docstring도 "recommend의
   후보 게시 전용"이라고 밝히고 있다 — 이 함수가 만드는 이벤트는 애초에 `pin.published`였어야
   한다. `pins/api.py`는 다른 모듈 소유 파일이라 직접 고치지 않고, `flows.py`에서 payload는
   그대로 두고 `type`만 `pin.published`로 바꿔 새 `Event`를 만들어 기록했다(`flows.py` 모듈
   docstring에 이유 기록). **pins 세션(또는 루트)이 `pins/core.py::pin_created_event` 호출을
   `create_ai_pin` 안에서 `pin.published` 전용으로 바꾸는 게 근본 수정** — 그러면 이 우회
   코드는 지워도 된다.

## data-model.md 대비 스키마 차이 (루트 확인 필요)

`candidates`에 `lat`/`lng`(Float)를 추가했다 — `docs/data-model.md` 144-150행의 candidates
정의엔 없는 컬럼이다. `pins_api.create_ai_pin(lat=..., lng=...)`를 부르려면 좌표가 필요한데
`places` 모듈이 아직 비어 있어(온디맨드 조회 불가) 후보 생성 시점에 좌표를 직접 들고 있는
수밖에 없었다 — `pins` 테이블이 `place_id`와 별개로 자기 `geom`을 갖는 것과 같은 이유
(차원 압축, architecture.md 3층 모델). `region_id`도 `regions` 테이블이 아직 없어 FK 없이
컬럼만 뒀다. **data-model.md에 이 두 컬럼을 반영할지, 아니면 후속 세션(근거 조립/후보 생성
파이프라인)이 실제로 값을 채울 때 재검토할지는 루트 결정이 필요하다.**

## 가볍게 훑거나 생략해도 되는 것

- `router.py`/`main.py` 등록 — 이 계획 문서는 `flows.py` 자체만 다루고 라우터를 언급하지
  않는다. `recommend/CLAUDE.md`의 나머지 책임(run 생성, 근거 조립, 실격 필터, 선호 순위,
  반경 넓히기/재시도, funnel)은 이번 범위 밖 — `docs/api-spec.yaml`의 `recommend` 태그
  엔드포인트 대부분이 아직 없다.
- `evidence_lines`/`regions`/`exclusions` 테이블 — 후속 세션 몫.
- `core.check_run_ready`가 `done`이 아닌 모든 상태(collecting_evidence/awaiting_region_confirm/
  executing/failed)를 동일하게 `NOT_READY`로 묶는다 — `failed`를 별도 코드로 구분할지는
  결정 이슈로 남겨둠(아래).

## 루트 확인·결정 필요 (모아서)

1. **위 "꼭 읽어야 할 것" 3번** — `authz.guard.require()`를 non-FastAPI 함수에서 `Depends`
   없이 직접 호출하는 패턴이 정식 지원 대상인지, 아니면 `authz.guard`에 별도 진입점을
   추가해야 하는지. `shortlist`도 같은 패턴이 필요할 가능성이 커서 이번에 정리하면 좋다.
2. **4번(pins.api 이벤트 타입 버그)** — `pins` 세션이 근본 수정할 항목으로 전달 필요.
3. **candidates.lat/lng 스키마 차이** — data-model.md 반영 여부.
4. **`check_run_ready`의 `failed` 처리** — NOT_READY로 뭉뚱그릴지, 별도 코드/화면이
   필요한지(`RECOMMEND_FAILED`는 파이프라인 실행 중 실패를 위한 코드라 이미 완료된 실패
   run을 게시 시도하는 경우와는 다른 상황).
5. (이관) **pins/for_Root.md가 남긴 "create_ai_pin의 Principal 구성"** — 이번엔 실제로
   `Principal`을 만들 필요가 없어(3번 항목 참고, authz.guard.require가 알아서 처리) 이
   결정은 여전히 미룰 수 있었다 — 참고로만 남김.
