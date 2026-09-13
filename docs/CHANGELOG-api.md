# API 스펙 변경 이력

`docs/api-spec.yaml`이 바뀔 때마다 여기 기록한다. 프론트 담당자는 이 파일을 구독해서 변경을 즉시 확인한다.

## 2026-09-11 — 비구성원 응답: 403 → 404 (PR #71 멘토 리뷰 대응)

`pins`를 비롯한 보호 리소스에서, 요청자가 해당 지도의 구성원이 아닐 때의 응답이 403에서
404로 바뀐다(`docs/permissions.md` "권한을 어디서 강제하는가"). 존재 여부 자체를 비구성원에게
노출하지 않기 위함 — 이미 비공개 핀에 적용 중이던 원칙을 모든 보호 리소스로 확장한 것이다.

또한 `/auth/kakao/callback`에 `security: []`를 명시 — 로그인 전 콜백이 전역 `cookieAuth`
요구사항의 예외임을 스펙에 정확히 반영(기존엔 누락돼 있었음).

**FE 영향**: 지도 접근 실패 처리 로직에서 403 분기를 보고 있었다면 404도 같은 방식(접근 불가
안내)으로 처리하도록 확인 필요. 403은 이제 "구성원이지만 버튼이 disabled였어야 하는 상황"만
의미한다(`docs/errors.md`).

## 2026-09-06 — 9/4 결정 3건 + 계약 갭 2건 반영 (#46, #47)

itsmedoyun님이 이슈로 제안한 내용을 검토 후 그대로 반영. 상세 근거는 각 이슈 본문 참고.

**#46 — 9/4 회의 결정 3건 (#45)**
- `MapCreateRequest`·`Map`: `region_hint` 제거, `start_date`·`end_date` 추가 (#22 여행 기간). `data-model.md`의 `day_count`도 함께 제거
- `Pin`: `created_by`·`created_by_display_name` 추가, `GET /maps/{mapId}/pins`에 `created_by` 필터 추가, `Member.color` 제거 (#26 구성원 필터)
- `POST /maps/{mapId}/route`("동선 짜주기") 신설, `GET`은 마지막 계산 결과만 반환하도록 summary 정정, `PUT /maps/{mapId}/shortlist/order`(수동 정렬) 신설, `docs/events.md`의 `route.recalculated`·`shortlist.changed` 설명 정정 (#30)
- **FE 영향**: `Member.color` 제거만 파괴적. `contracts/mocks`의 색 사용 3곳(seed.ts, handlers/maps.ts)도 함께 제거. 나머지는 전부 추가.

**#47 — 계약 갭 2건**
- `realtime` 태그 신설, `GET /maps/{mapId}/events`·`GET /maps/{mapId}/events/me` + `Last-Event-ID` 헤더 파라미터 추가
- 이벤트 11종 페이로드 스키마 추가 (`PublicEvent` 8종 / `PrivateEvent` 3종, `event` 값으로 판별되는 유니온)
- `NotReady`·`Forbidden`·`RecommendFailed`·`IdempotencyConflict` 응답 컴포넌트 추가. 앞 3개는 각각 `POST /maps/{mapId}/runs`(409)·`PATCH /runs/{runId}/evidence`(403)·`POST /runs/{runId}/execute` & `GET /runs/{runId}/result`(500)에 명시. `IdempotencyConflict`는 컴포넌트만 정의(붙일 엔드포인트는 #48 결정 대기)
- `info.description`에 "401은 전역" 한 줄 추가, 엔드포인트별 401 반복 표기 안 함
- **FE 영향**: 추가만 있고 삭제·변경 없음. SSE 이벤트는 `event` 값으로 좁혀지는 판별 유니온이라 `evt.data`가 타입으로 잡힌다.

**docs/errors.md** — PR #49(backend/common 에러 미들웨어)에서 제안한 `VALIDATION_ERROR`·`NOT_FOUND`·`INTERNAL_ERROR` 3개 코드 추가(봉투 통일용, 화면 상태 아님).

검증: `npm run lint:spec && npm run gen:types && npm run typecheck && npm test` 전부 통과.

## 2026-09-02 (2) — 목 서버 구축 + 스펙 오류 수정 (이슈 #38)

- `contracts/` 패키지 신설: `openapi-typescript` 타입 생성 + `msw` 목 서버(24개 경로 전부, 상태를 가진 인메모리 스토어) + 시나리오 5종. 사용법은 `contracts/README.md`.
- **`docs/api-spec.yaml` 자체 오류 수정** (`@redocly/cli lint` 통과 확인, 이전엔 25개 에러로 무효한 스펙이었음):
  - `nullable: true`(OAS 3.0 문법)를 OAS 3.1 문법인 `type: [T, "null"]`로 4곳 수정 (`Pin.source_run_id`, `EvidenceLine.fact_key`, `Candidate.published_pin_id`, `ShortlistItem.visit_order`)
  - 응답 객체에 `description` 누락 18곳 보강
  - operation `summary` 누락 3곳 보강 (`POST /auth/logout`, `GET /maps/{mapId}`, `GET /maps/{mapId}/shortlist`)
  - `Pin` 스키마에 `price_bucket` 필드 추가 (미사용 컴포넌트였던 `PriceBucket`을 실제로 연결)
- **프론트 영향**: 타입을 재생성해야 한다(`npm run gen:types`). `Pin.source_run_id` 등 4개 필드의 TS 타입이 `string | null`(과거엔 사실상 `string`으로만 추론됨)로 바뀐다 — null 체크 추가 필요.

## 2026-09-02 (1) — 초기 계약 확정

- `docs/api-spec.yaml` 최초 작성. `최종기획안.md` 4·5·6절 + 기술 멘토링 피드백 기반.
- 확정 사항: `PlaceSource` 어댑터 추상화(D1), `place_facts` 자체 DB(D2), 프리시딩(D3), `unknown_policy` 차등(D4), 동선 v1 유지/카톡파싱 v2(D5), SSE 확정(D6).
- 프론트 영향: 전 엔드포인트가 신규. `docs/openapi-workflow.md`대로 타입 생성 + 목 서버 세팅부터 시작하면 됨.
- 열린 항목(스펙에 자리만 잡아둔 값 — 결정되는 대로 갱신): 지도 생성 입력 필드, 중복 핀 판정 기준, 재시도 3회 상한 집계 단위, N의 정의, 구성원 색 배정 방식, 화면 구조(데스크톱 vs 모바일 — 응답 형태 자체엔 영향 적음).
