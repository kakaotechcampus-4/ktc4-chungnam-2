# backend/recommend

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/api-spec.yaml`(`recommend` 태그 전체), `docs/data-model.md`(`recommend_runs`, `evidence_lines`, `regions`, `candidates`, `exclusions`), `docs/constraints.md`.

## 책임

가장 넓은 모듈이다. 기획안 3절 에이전트 루프의 코드 담당 단계 전부.

- run 생성, 근거 조립(①②), 근거 토글/추가
- 지역 확인(5-6-1 signature 저장·무효화)
- 실격 필터 실행(③-a-2, `docs/constraints.md`를 그대로 순회)
- 선호 순위 결과 조립(③-b는 `llm` 호출 결과를 받아 정렬)
- 대안 반영(④) — 비공개 candidate 생성
- 게시(`/candidates/{id}/publish`) — `pins`에 공개 핀 생성 요청
- 반경 넓히기, 재시도(제외목록에 넣고 재실행), funnel 집계

## 하지 않는 것

- 모델 호출 자체 (→ `llm`). 이 모듈은 `llm`에 "이 근거들을 구조화해줘" / "이 후보들 순위 매겨줘"라고 요청만 하고 프롬프트를 직접 다루지 않는다.
- 장소 라벨링 (→ `places`/`seeding`). 캐시 히트/미스만 확인하고, 미스면 `seeding`의 온디맨드 폴백 경로를 호출한다.

## 넘지 말 것

- **`docs/constraints.md`의 `unknown_policy`를 그대로 적용한다.** 안전 조건이 unknown인데 통과시키는 코드를 짜면 최우선 성공지표(실격 위반율 0%)가 깨진다 — 이 부분은 반드시 계약 테스트로 고정한다.
- 5-6 실격 필터 순서(반경→영업종료→실격조건→중복제외→정렬)를 바꾸지 않는다. 순서가 깔때기 표시(funnel)의 의미를 결정한다.
- 추천 횟수 상한은 없다. 「추천 받기」 1번에 크레딧 1이다(#432, #949, `docs/credits-reviews.md`): `flows._create_run`이
  모델(②) 전에 `credits.api.check_can_spend`, run INSERT와 같은 트랜잭션에서 `credits.api.charge`를 부른다. 가격 숫자는
  여기 적지 않는다(`credits/constants.py`). 「다시 찾기」·「근거 고치기」는 크레딧을 쓰지 않는다. 환불은 **첫 실행이 0곳일
  때 하나뿐이다**(`flows._search_and_store`가 같은 트랜잭션에서 `credits.api.refund`, #1015). 그 밖의 실패는 run과 차감이 함께
  롤백된다. 차감·환불을 부르는 곳과 환불 조건의 정본은 `docs/credits-reviews.md` 3.2 표다(이유는 3.3절, 검사가 코드와 맞춘다, #1479) — 바꿀 때는 거기를 고치고 여기는 가리키기만 한다. `attempt_no`와 `lock_requester_attempts`(#811)는 번호를 매기려고 남긴다.

## 추천 위치 기준이 바뀌면 같이 바뀌는 곳 (#1483)

기준은 "보이는 지도 가운데 한 점의 원"이고(#1331), 반경은 사용자가 고른 m다(#1416, 기본·범위는 `core.DEFAULT_RADIUS_M`,
`MIN_RADIUS_M`, `WIDEN_LIMIT_M`). 가운데 한 점으로 원을 만드는 함수는 `flows._center_region` 한 곳이다. 한 주에 기준을 세 번
바꾸면서 같이 바뀌어야 할 곳을 하나씩 찾아야 했다(멘토 리뷰). 기준을 바꿀 때는 아래를 같이 본다.

| 자리 | 지금 |
|---|---|
| run 생성 `flows.create_run`, `_create_run` | `center` 필수 — 없으면 422 `VALIDATION_ERROR` |
| 요청 모델 `schemas.RunCreateRequest.center` | **필수다**(#1354). 없으면 요청 모델이 422 `VALIDATION_ERROR`로 막고 `flows.create_run`은 `center`를 필수 인자로 받는다. 운영 배포(2026-11-08, #1528)로부터 키 보관 기간(`core.IDEMPOTENCY_RETENTION` 24시간)이 지나 `center` 없는 옛 키의 재시도 호환(멱등 해시의 center 없음 갈래, 같은 키면 그 run을 돌려주던 분기)을 지웠다. 옛 run(`origin_lat`·`origin_lng` 없음)의 다시 추천·넓히기는 저장된 지역을 쓰므로 그대로 동작한다 |
| 멱등 동일성 `core.idempotency_request_hash` | `center`(필수)와 `radius_m`(3000이 아닐 때만)이 들어간다. `center`가 있는 요청의 해시 모양은 바꾸지 않는다(`test_idempotency_811.py`가 고정) |
| readiness 근처 정예 수 `flows._curated_nearby` | `center`가 있으면 `_center_region`, 없으면 핀 앵커(옛 기준) |
| 미리 돌려 보기 `flows.preview_filter`(agent 진단) | agent는 화면이 없어 보이는 가운데를 모른다 → 핀 앵커(옛 기준, `_default_circle_and_anchors`). 교체 전 로직은 태그 `legacy/recommend-pin-anchor`로 남기고, 이 경로가 옛 기준을 쓰는 동안 코드에서 지우지 않는다 |
| 여행 지역 밖 판정 `OUTSIDE_TRIP_REGION` | run과 같은 원(`places.api`의 경계 판정) |
| 화면 | 지도 원과 범위 문구는 readiness `radius_m`, 넓히기 확인 창은 `default_radius_m`·`next_default_radius_m`(#1468) |
| 계약 | `docs/api-spec.yaml`의 `POST /maps/{mapId}/runs`(`center`, `radius_m`), `Readiness.radius_*`, `docs/CHANGELOG-api.md` |
| 테스트 대역 | `backend/conftest.py`의 `_run_center_from_pins` — `center` 없이 run을 만드는 옛 테스트에 핀 평균 중심을 채운다(`flows.create_run` 호출과 `POST /maps/{mapId}/runs` 본문 둘 다). `center` 없는 요청 자체를 보는 시험은 `@pytest.mark.no_center_shim`으로 끈다 |

## 완료 정의

- `docs/api-spec.yaml` `recommend` 태그 엔드포인트 전체 구현 + 단위 테스트
- `docs/constraints.md` 표의 각 `fact_key`에 대해 `unknown_policy`대로 필터링되는지 개별 테스트 (안전 조건 unknown → 제외 확인이 최우선)
- 5-6-1 지역 겹침/안 겹침 케이스, "두 지역 각각 찾기" signature 재확인 흐름 테스트
- 「다시 추천 받기」 시 이전 후보가 `exclusions`에 들어가고 다음 실행에서 제외되는지 테스트

## 우선순위

`llm` 모듈의 프롬프트 품질을 기다리지 말고 **스텁 응답으로 먼저 오케스트레이션·API·이벤트를 전부 통합**한다. FE+BE 코어 루프 데모가 AI 품질보다 먼저다 — `contracts/mocks`가 이 스텁의 참고 모양이다.

## 코드 품질

`docs/code-quality.md` 참고. 이 모듈은 특히 도메인 규칙(`unknown_policy`, 가드레일) 준수가 스타일보다 훨씬 중요한 리뷰 대상이다.
