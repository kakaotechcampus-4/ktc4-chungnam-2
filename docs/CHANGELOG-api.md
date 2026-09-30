# API 스펙 변경 이력

`docs/api-spec.yaml`이 바뀔 때마다 여기 기록한다. 프론트 담당자는 이 파일을 구독해서 변경을 즉시 확인한다.

## 2026-10-01 — 장소 이름 검색 `GET /places/search` 신설 (#180, #147)

v1의 핀 입력은 **이름 검색 → 결과에서 골라 찍기**와 **지도 길게 눌러 좌표로 찍기** 둘뿐이다(#147). 그런데 스펙에 검색 엔드포인트가 없어 FE가 검색 결과의 `place_id`를 얻을 곳이 없었다.

- `GET /places/search?q=&lat=&lng=&limit=` → `PlaceSearchResult[]`(`place_id`, `place_name`, `lat`, `lng`, `category?`, `address?`, `place_source?`). 로그인만 필요(지도 구성원 여부와 무관). `q`는 1~50자, `lat`·`lng`는 함께 보내면 가까운 곳 우선, `limit` 기본 10·최대 15.
- 응답 필드 이름은 핀 생성 요청의 `place_name`과 같게 맞췄다(그대로 보낼 수 있다). 사용자당 호출 상한(기본 분당 30회) 초과 시 **429 `RATE_LIMITED`**(새 코드).
- 결과 0개는 빈 배열 그대로다(가드레일 2, 지어내서 채우지 않는다). 지도 API가 전부 실패하면 **503 `PLACES_UNAVAILABLE`**(새 코드, `docs/errors.md`).
- 검색 결과는 서버 DB에 저장하지 않는다(#53). v1은 카카오 하나만 켠다(2026-10-01).
- **핀 만들기 연결**: `POST /maps/{mapId}/pins`의 `source: "search"`는 검색 결과의 `place_id`·`place_name`·`lat`·`lng`를 **그대로** 보낸다. 새 필드는 없다 — 설명만 명확히 했다. `source: "link"`/`link_url`은 "v1에서 받지 않음(422)"으로 표시했다(#147).
- 신뢰 모델: 좌표는 클라이언트가 echo하지만, `source: "coordinate"`도 이미 임의 좌표를 받으므로 위험이 늘지 않는다. 서버는 캐시에 그 `place_id`가 있으면 좌표 일치를 확인한다(구현 재량, #180).

**FE 영향**: 타입 재생성(`npm run gen:types`), 목 서버에 `GET /places/search` 핸들러 추가됨. 검색바 → 결과 목록 → 핀 생성 연결.
**BE 후속**: `backend/places`(`search_by_name`), `backend/pins`(검색 경로 resolve) — #180.

## 2026-09-30 (두 번째) — FE 스펙 갭 6건 + 숙소 반응 불가·「기타」·탈퇴 처리 (#154, #155)

FE가 디스코드로 올린 10건 중 스펙에 없거나 틀린 것을 루트가 검증해 반영했다. 모듈 구현은 이 스펙을 기준으로 한다(스펙보다 구현이 앞서지 않는다).

**추가 (FE 영향: 타입 재생성 `npm run gen:types`)**
- `Candidate`·`Pin`에 `reason`, `member_fulfillment`(`MemberFulfillment{satisfied,total,by_member?}`), `place_source`(`PlaceSource{provider,url?}`) — 가드레일 5. 게시된 뒤에도 Pin에 유지. 모두 선택 필드(AI 추천 핀만).
- `Pin.my_reaction: Reaction | null` — 「♥ 2 · 나」 칩, 「의견 취소」 링크용.
- `GET /pins/{pinId}/reactions` → `Reaction[]` — 핀 상세 「구성원 의견」. `Reaction`에 `reason_chip_ids`, `display_name` 추가.
- `GET /invites/{token}` → `InviteSummary` (map_id 미포함) — 로그인 불요. 404 `INVITE_NOT_FOUND`, 410 `INVITE_EXPIRED`(수락 API에도 동일).
- `PATCH /auth/me {display_name}` → `User` — 계정 단위 이름 수정(지도별 이름은 두지 않는다).
- `RecommendRun.default_radius_walk_min`, `POST /runs/{runId}/widen`이 `RecommendRun`을 돌려주고 상한 초과 시 409 `WIDEN_LIMIT`. 폭 +5분/회, 상한 도보 30분(`docs/constraints.md`, 조정 가능한 상수 — **제안값**).
- `Category`에 `기타` 추가. 숙소 핀은 `permissions.can_react=false`, 반응 요청 시 422 `REACTION_NOT_ALLOWED`(`docs/permissions.md`, #154).

**바로잡음 (동작 변화 없음)**
- 재시도 상한 문구 3회 → 5회(#31 확정값이 이미 기획안·errors.md에 있었고 api-spec만 옛 값이었다).
- `DELETE /pins/{pinId}` 권한 "결정 이슈 미결" → 구성원 누구나(#25). `DELETE /pins/{pinId}/reaction`은 "핀 되돌리기"에서 "내 반응 취소"로.
- `/auth/withdraw`: 반응·사유·근거 줄 삭제, 핀 유지 + "탈퇴한 구성원" 표시(#155).

**BE 후속** (마이그레이션 번호는 루트가 배정 — 0015 recommend: 숙소 enum 제거(#146)+candidates 컬럼, 0016 pins: 기타 enum+pins 컬럼)
- pins: 의견 목록·`my_reaction`·`reason_chip_ids` 응답(DB 컬럼은 이미 있음), 숙소 반응 차단, 기타, AI 핀 3필드 복사, `delete_reactions_by_user`
- recommend: Candidate 3필드(`member_fulfillment`은 지금 항상 `{}`), widen 폭/상한, `delete_evidence_lines_by_author`
- maps: `GET /invites/{token}`+에러코드(마이그레이션 없음) · auth: `PATCH /auth/me`, 탈퇴 시 두 함수 호출

## 2026-09-30 — 추천 카테고리에서 숙소 제외, RecommendCategory 신설 (#145)

숙소를 AI 대안 추천 대상에서 뺐다(#145). 숙소 핀은 그대로 찍고 반응을 남길 수 있어서 핀 쪽
`Category`는 바꾸지 않고, 추천에 쓰는 카테고리만 따로 나눴다.

- `RecommendCategory` 신설 — `[음식점, 카페, 관광지]`
- `POST /maps/{mapId}/runs` 요청의 `category`: `Category` → `RecommendCategory`
- `RecommendRun.category`: `Category` → `RecommendCategory`
- `GET /maps/{mapId}/recommend/readiness` 응답의 키를 `RecommendCategory`로 한정 — 숙소 키는 오지 않는다
- 목 서버: readiness에서 숙소 제외, 지역 확인 대기 시나리오의 run 카테고리를 숙소 → 관광지

**FE 영향**: 타입 재생성 필요(`npm run gen:types`). 숙소 핀에서는 추천 버튼과 대안 추천 진입점을
보이지 않게 한다. readiness 응답에 숙소 키가 없다고 가정하고 그리면 된다.

**BE 영향**: `backend/recommend`의 카테고리 목록과 DB enum `recommend_category`에서 숙소 제거
(마이그레이션), `capacity_min` 조건 제거. `backend/llm` 사유 구조화 출력의 `capacity_min` 제거.
후속 이슈로 나눈다.

## 2026-09-28 — 내 지도 목록(`GET /maps`) 신설, 지도 생성에 지역(선택) 추가 (#22, #24 변경)

PR #132(Solquick24) 제안을 루트가 검증 후 승인 — FE 회의 후속 결정(최종기획안 15절
2026-09-28 항목)으로 9/4에 확정했던 #22·#24 두 결정이 바뀌었다. 이슈 자체는 재오픈하지
않고 코멘트로만 갱신됐다(PR #131 본문에 "별도 PR로 고친다"고 명시) — 팀 컨벤션상 아쉬운
지점이라 별도로 다뤘다.

**#24 — 로그인 직후 진입점이 "지도"에서 "내 지도 목록"으로.** 목록을 줄 엔드포인트가 없어서
새로 만든다.

- `GET /maps` 신설: 내가 구성원인 지도를 최근 생성순으로 `Map[]`로 돌려준다. 속한 지도가
  없으면 빈 배열이다. `POST /maps`와 같은 이유로 에러 응답을 따로 선언하지 않는다 — 특정
  `mapId`를 대상으로 한 멤버십 판정이 없어(전체 목록 조회라) 404가 성립하지 않고, 이
  `maps` 태그는 401도 엔드포인트별로 선언하는 관례가 아니다(`/auth/*`·realtime SSE만
  선언). PR #132 원안 그대로 두고, 루트가 별도로 고칠 게 없었다.
- 초대 링크로 들어온 구성원은 목록을 거치지 않고 해당 지도로 바로 간다. FE 라우팅만의
  문제라 API 변경은 없다.
- 로그인 콜백 리다이렉트(`FRONTEND_LOGIN_REDIRECT_URL`, 기본 `frontend_base_url` 기준)는
  그대로다. `/`에서 목록을 보여줄지는 FE가 정한다.

**#22 — 지도 만들기 입력값에 지역 검색 추가.** 9/4의 "지역힌트 아님"을 뒤집는다.

- `MapRegion { label, lat, lng }` 스키마 신설. `MapCreateRequest.region`·`Map.region`에
  **선택 필드**로 붙는다.
- 지역이 없으면 지금처럼 첫 핀 좌표로 지역을 정한다(`architecture.md` 3절 프리시딩 트리거에
  반영).
- 시작일·종료일은 지금처럼 필수다.
- `data-model.md`의 `maps`에 `region_label`·`region_center`(둘 다 nullable, 둘 다 있거나
  둘 다 없음 — `CHECK` 제약)를 추가한다.
- 지역을 어디에 쓸지(첫 지도 위치 등)는 기획안 15-4에 미결로 남아 있다. 이번 변경은 값을
  받아 저장·반환하는 데까지다 — 막지 않는다.

**FE 영향**: `contracts` 타입이 이미 재생성됨(PR #132) — `Map`·`MapCreateRequest`에 optional
`region`, 목 서버에 `GET /maps` 핸들러 추가. 기존 호출은 그대로 동작한다.

**BE 후속**: `backend/maps`에 `GET /maps` 라우트, `region` 필드(스키마·모델·마이그레이션),
`member_count` N+1 방지가 필요 — 이슈로 안내.

## 2026-09-23 — PinCreateRequest.place_name 추가 (루트 결정)

프론트-백엔드 통합 감사에서 "핀 이름이 항상 빈칸으로 온다"는 게 확인됐다 — 원인은
`pins/core.py::to_pin_response`가 `place_name`을 채울 데이터 출처가 없어서였다. 장소
라벨링(가격·재료 등, `places` 모듈·#53 대기)과 달리 **이름은 사용자가 생성 요청 시점에 이미
들고 있는 값**(구글맵 링크·검색 결과)이라 `places` 파이프라인을 기다릴 필요가 없다고 판단해
바로 반영했다.

- `PinCreateRequest.place_name: string (maxLength 100)` 신설 — 필수 아님(좌표 경로는 이름이
  없을 수 있다).

**FE 영향**: 타입 재생성 필요(`npm run gen:types`). 핀 생성 UI(#16)에서 구글맵 링크·검색
결과의 이름을 이 필드로 같이 보내면 `Pin.place_name`에 그대로 저장·응답된다.

## 2026-09-22 — Candidate.permissions 추가 (#64 결정)

`Candidate` 스키마에 `permissions` 필드가 없어서 "게시할 수 있는지"(`recommend.publish`,
`candidate.requested_by` 본인만)를 FE가 판단할 방법이 없었다(#64). 다른 리소스와 같은 패턴으로
풀었다 — 새 필드를 만들지 않고 기존 공용 `Permissions` 스키마에 `can_publish`를 추가하고,
`Candidate`가 그 스키마를 참조하게 했다.

- `Permissions.can_publish: boolean` 신설
- `Candidate.permissions: Permissions` 신설

**FE 영향**: 타입 재생성 필요(`npm run gen:types`). `recommend` 모듈이 아직 없어 실제로 이 필드가
채워지는 엔드포인트는 없다 — 타입만 먼저 맞춰둔다.

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
