# API 스펙 변경 이력

`docs/api-spec.yaml`이 바뀔 때마다 여기 기록한다. 프론트 담당자는 이 파일을 구독해서 변경을 즉시 확인한다.

## 2026-09-19 (2) — 값 제약(길이·범위) 보강 (PR #94 멘토 리뷰 대응)

`reason_text`(maxLength 140)·`step`(1~8) 딱 둘만 값 제약이 있고 나머지 필드(문자열 82개,
숫자 25개)엔 아무 제약이 없다는 걸 멘토 리뷰에서 지적받았다. 두 갈래로 나눠 반영했다.

**코드에 이미 있는 검증을 명세로 끌어올림** — `pins/core.py::validate_create`가 이미
`-90<=lat<=90`, `-180<=lng<=180`을 검증하고 있었는데 명세에는 없었다. `PinCreateRequest`·
`Pin` 양쪽의 `lat`/`lng`에 `minimum`/`maximum`을 추가했다.

**코드에 근거가 없어 이번에 새로 정한 값** — 자유 텍스트라 악용·오류 여지가 있는 필드에
`maxLength`를 추가했다. 값 자체는 근거가 없으니 팀 확인이 필요하다.

- `title`(`Map`·`MapCreateRequest`): 100
- `place_name`(`Pin`): 100
- `display_name`(`User`·`Member`), `created_by_display_name`(`Pin`), `author_display_name`
  (`EvidenceLine`): 50
- `text`(`EvidenceLine`·`EvidencePatchRequest.add[].text`): 140 (`reason_text`와 같은 성격의
  자유 텍스트라 같은 값을 씀)
- `link_url`(`PinCreateRequest`): 2000 (사용자가 직접 붙여넣는 구글맵 링크)
- `reason_chip_ids`(`ReactionRequest`): 배열 `maxItems: 10`, 항목당 `maxLength: 50` (사전
  정의된 칩 목록에서 고르는 값이라 이 이상 올 이유가 없다)
- `Candidate.place_name`: 100 (`Pin.place_name`과 동일 근거)

짝이 안 맞던 것도 하나 고쳤다 — `ReactionRequest.reason_text`엔 `maxLength: 140`이 있는데
그 값을 그대로 돌려주는 응답 스키마 `Reaction.reason_text`엔 없었다. 맞췄다.

**FE 영향**: 없음. `openapi-typescript`는 `maxLength`·`minimum`·`maximum`·`maxItems`를
타입이나 주석 어디에도 반영하지 않는다(`description`만 반영) — 확인해보니 타입 재생성
결과가 이전과 바이트 단위로 동일했다. 프론트가 이 값을 알아야 하면 명세를 직접 참고해야 한다.

**후속 필요 — 아직 서버가 안 막는다**: `title`·`place_name`·`display_name`·`text`·`link_url`·
`reason_chip_ids` 6개는 명세에만 추가됐고, 실제 Pydantic 스키마(`maps/schemas.py`·
`llm/schemas.py`·`pins/schemas.py`)는 아직 그냥 `str`/`list[str]`이라 이 값을 초과해도
서버가 거부하지 않는다(`reason_text`만 `pins/schemas.py`에 `Field(max_length=140)`으로 이미
강제됨). `Candidate.place_name`은 `recommend` 모듈 자체가 아직 없어서 해당 없음. `lat`/`lng`는
`pins/core.py`가 이미 강제하므로 문제없다. 각 모듈(`maps`·`llm`·`pins`) 담당자가
`Field(max_length=...)`를 추가하는 후속 이슈가 필요하다 — 다른 모듈 파일이라 여기서 직접
고치지 않았다.

## 2026-09-19 — 도메인 응답 스키마에 required 추가 (PR #94 멘토 리뷰 대응)

`Map`·`Invite`·`Member`·`Pin`·`Reaction` 5개 응답 스키마에 `required`가 하나도 없었다는 걸
멘토 리뷰에서 지적받았다. `MapCreateRequest` 등 요청 스키마는 `required`를 챙겼지만 응답
스키마는 최초 작성(2026-09-02) 이후 아무도 다시 손보지 않은 것으로 확인됐다 — 의도적 설계가
아니라 누락이었다.

각 모듈의 실제 구현(`maps/core.py`, `pins/core.py`)을 근거로, **항상 채워지는 필드만**
`required`로 추가했다. 다른 모듈 의존으로 못 채우는 필드(`Map.confirmed_count`,
`Member.display_name`·`online`, `Pin.place_name`·`created_by_display_name`·`price_bucket`·
`checks`·`source_run_id`, `Reaction.reason_text`)는 그대로 optional로 남겼다 — 이 필드들의
"없을 수도 있음"이 이제 명세에 정식으로 드러난다.

- `Map`: `required: [id, title, start_date, end_date, member_count]`
- `Invite`: `required: [token, url, expires_at]` (전부 항상 채워짐)
- `Member`: `required: [user_id]`
- `Pin`: `required: [id, map_id, category, kind, visibility, lat, lng, created_by, reaction_summary, permissions]`,
  `reaction_summary` 내부도 `required: [like, neutral, against]`
- `Reaction`: `required: [pin_id, user_id, type]`

타입을 재생성해서(`npm run gen:types`) 확인하는 과정에서 **목 서버 자체의 버그 2건**을 발견해
같이 고쳤다 — `contracts/mocks/seed.ts`의 `pinCafe1`과 `contracts/mocks/handlers/recommend.ts`의
후보 게시 핀이 `created_by`를 채우지 않고 있었다(실서버는 이 필드를 항상 채운다). `required`가
없던 동안은 타입 에러로 안 잡히고 조용히 넘어갔던 것이다.

`User`·`FilterCounts`·`Readiness`·`EvidenceLine`·`Region`·`RecommendRun`·`Candidate`·
`RecommendResult`·`ShortlistItem`·`Route`·`Check`는 이번에 손대지 않았다 — 해당 모듈(auth·
recommend·shortlist 등)의 실제 구현을 확인하지 않고 `required`를 추측해서 넣으면 이번에
고친 것과 같은 종류의 실수(구현과 안 맞는 계약)를 새로 만들 수 있어서, 각 모듈 구현이 확인된
뒤 같은 방식으로 정리하는 게 맞다고 판단했다.

**FE 영향**: 타입 재생성(`npm run gen:types`) 필요. 위 5개 스키마의 필드 대부분이
`T | undefined`에서 `T`로 좁혀진다 — 기존에 옵셔널 체이닝(`?.`)이나 널 체크를 했던 코드는
그대로 동작하고, 새로 에러가 나는 방향은 없다. `redocly lint`·`tsc --noEmit`·`vitest`
전부 통과 확인(경고 60개, 구조 변경 전과 동일).

## 2026-09-14 — maps 착수 반영: 404 커버리지 + invite.create 권한 결정 (#4)

`maps` 모듈(#4·#19) 구현과 함께 발견된 계약 갭을 반영했다.

- `GET /maps/{mapId}`, `POST /maps/{mapId}/invite`, `GET /maps/{mapId}/members`에 `404`
  (신규 `NotFound` 컴포넌트) 추가 — 비구성원 응답은 존재 자체를 흘리지 않는다는 기존 원칙과
  동일. `/invites/{token}/accept`는 계속 401만 쓴다(토큰 존재 여부를 노출하지 않으려고
  없는 토큰과 만료된 토큰을 구분하지 않는 설계, `maps/core.py` 참고).
- **결정 — 초대 링크 발급은 구성원 누구나(#4)**: `invite.create` 액션을 `docs/permissions.md`
  `member.actions`에 추가하고 `authz/policy.py`에 동기화(정본 대조 테스트 통과 확인).
  owner 전용으로 제한하는 안은 기각 — 이 프로젝트의 기존 권한 패턴(`pin.delete`,
  `shortlist.add/remove` 등 대부분 "구성원 누구나")과 일관되게 유지.

**FE 영향**: 타입 생성 시 위 3개 오퍼레이션에 404 케이스가 새로 잡힌다(기존 `Error` 스키마
재사용). 초대 발급 버튼은 모든 구성원에게 노출해도 된다.

## 2026-09-13 — 403 응답 커버리지 확대 (#67)

authz(`can()`)가 실제로 권한 판정을 하는 6개 오퍼레이션에 `403` 응답을 명시했다(기존엔
`PATCH /runs/{runId}/evidence` 한 곳뿐이었다): `POST /maps/{mapId}/pins`,
`DELETE /pins/{pinId}`, `PUT /pins/{pinId}/reaction`, `DELETE /pins/{pinId}/reaction`,
`POST /maps/{mapId}/shortlist`, `DELETE /shortlist/{itemId}`.

조회(GET) 엔드포인트는 멤버십만 보고 액션 판정이 없어(`require_map_member()`) 대상에서
뺐다 — 비구성원은 여기서도 여전히 404.

**FE 영향**: 타입 생성 시 위 6개 오퍼레이션 응답에 403 케이스가 새로 잡힌다. 이미 존재하던
`Error` 스키마 재사용이라 새 타입은 아니다.

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
