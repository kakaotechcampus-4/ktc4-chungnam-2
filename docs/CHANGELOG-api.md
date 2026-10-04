# API 스펙 변경 이력

`docs/api-spec.yaml`이 바뀔 때마다 여기 기록한다. 프론트 담당자는 이 파일을 구독해서 변경을 즉시 확인한다.

## 2026-10-04 — FE 화면 구현에서 나온 필드 6건, 반대 사유 칩 API (#60)

프론트가 Figma를 구현하다 스펙에 없어 우회하던 값들이다. 모두 **추가**이고 기존 필드는 안 바뀐다. 서버(pins·maps)가 채울 때까지 새 필드는 **선택**으로 두고(서버가 못 채운 응답이 계약 테스트를 깨지 않게), 목 서버는 항상 채워 준다. 서버 이슈가 닫히면 필수로 바꾸고 다시 알린다.

- **`Pin.created_at`**(date-time): 핀이 지도에 올라온 시각. 「최근 추가 순」 정렬·「최근 핀으로 이동」·「10분 전」용. AI 추천 핀은 「지도에 올리기」를 누른 시각이다.
- **`FilterCounts.members_with_opinion`·`members_total`**(`GET /maps/{id}/counts`): 「2/4명이 의견을 남겼어요」의 2와 4. 반응을 하나라도 남긴 구성원 수(탈퇴자 제외)와 현재 구성원 수.
- **`Map.pin_count`·`InviteSummary.pin_count`**: 「핀 12개」. 초대 요약은 핀의 이름·위치 없이 개수만 준다.
- **`Member.role`**(`owner`·`member`): 방장 표시. `member.joined` 이벤트의 Member에도 같다.
- **`reaction.changed` 이벤트**: 페이로드에 `user_id`·`display_name`·`type`(삭제면 null)을 더한다 — 「지우님이 반대 의견을 남겼어요」. 사유 내용은 싣지 않는다.
- **`GET /categories/{category}/reason-chips`**(새 경로, #60): 카테고리별 반대 사유 칩 `[{id, label, fact_key?}]`. 목록의 정본은 `docs/constraints.md` 「반대 사유 칩」(음식점 6·카페 4·관광지 3·공통 2). `reason_chip_ids`에는 **id**를 보낸다 — 이름("매워요")을 그대로 보내던 것을 바꿔야 한다. 그 카테고리 목록에 없는 id는 `PUT /pins/{id}/reaction`이 422 `VALIDATION_ERROR`.
- **FE 영향**: 타입 재생성(`npm run gen:types`). 칩 UI는 이 API로 목록을 받아 그리고 id를 보낸다. 새 필드는 서버 구현 전에는 비어 올 수 있으니(실서버 연결 시) 지금 쓰는 우회 코드는 서버 이슈가 닫히고 필수로 바뀐 뒤에 걷는다.
- 서버 작업: pins(created_at·counts·칩·반응 이벤트), maps(pin_count·role).

## 2026-10-03 — 카테고리 정의 한 곳, 「기타」 핀 반응 불가 (#280)

- 카테고리마다 핀 생성(`pinnable`)·반응(`reactable`)·추천(`recommendable`) 가능 여부를 `backend/common/categories.py` 한 곳에서 정한다. 스펙 `Category`·`RecommendCategory`, DB enum, 목 서버(`contracts/mocks/categories.ts`)와 대조 테스트로 맞춘다. enum 값은 그대로다.
- **v1에 숙소와 기타는 없다.** 둘 다 자체 DB에 없어 핀으로 만들 수 없고(#191), 세 성질이 모두 거짓이다. 값은 스키마 호환으로만 남는다. 다시 살리는 방법은 v2에서 검토한다(#281).
- 그래서 「기타」 핀도 숙소처럼 `permissions.can_react=false`, `PUT /pins/{pinId}/reaction`은 422 `REACTION_NOT_ALLOWED`, `GET /pins/{pinId}/reactions`는 빈 배열이다(이전 #157은 「기타는 일반 핀과 같다」). v1에서 기타 핀은 만들어지지 않으므로 화면 동작은 같다.
- **FE 영향**: 없음. 스키마가 그대로라 타입 재생성도 필요 없다.

## 2026-10-02 (다섯 번째) — 스펙에 빠져 있던 응답 선언 정리, 충족 집계, 안전 사유 규칙 (#246, D11)

점검 루프 1회차에서 코드는 합당하게 동작하는데 스펙에 선언이 없던 곳을 정리한다(사용자 결정: 권고대로 스펙을 코드에 맞춘다).

- **`POST /maps/{mapId}/runs`**: 429 `RETRY_LIMIT`(5회 상한은 카테고리 무관 개인 단위라 새 run에도 걸린다, #31), 500 `RECOMMEND_FAILED` 추가.
- **`/runs/{id}/execute·result·widen·retry·regions/confirm`**: 403 `FORBIDDEN` 추가 — run 실행계는 run을 요청한 본인만(`docs/permissions.md`, 가드레일 1).
- **`PATCH /runs/{id}/evidence`**: 404 `NOT_FOUND`(없는 근거 줄 id).
- **`POST /candidates/{id}/publish`**: 409 추가 — `NOT_READY`(run이 아직 done이 아님) 또는 `PIN_DUPLICATE`(`detail.pin_id`). 비작성자는 스펙 그대로 **404 `AI_PIN_PRIVATE`**이고 **코드를 스펙에 맞춘다**(구성원에게도 남의 후보 존재를 숨긴다, D15). 동시 게시의 `IDEMPOTENCY_CONFLICT`는 `PIN_DUPLICATE`로 정리한다(`errors.md`의 `IDEMPOTENCY_CONFLICT`는 Idempotency-Key 충돌이다).
- **`PUT /maps/{mapId}/shortlist/order`**: 422(`item_ids`가 현재 리스트와 맞지 않음).
- **`MemberFulfillment.total`**: 실격 사유(required)를 낸 구성원도 센다(G1). 후보는 실격을 통과했으므로 충족으로 센다 — 선호가 없는 run에서도 "N명 중 N명 충족"으로 가드레일 5의 설명이 남는다.
- **안전 조건 사유는 배지와 무관하게 실격**(`docs/constraints.md` "안전 조건 사유는 배지와 무관하게 실격이다"): △·♥·「+」로 남긴 알러지 사유도 `wants=false`면 실격이다. ②는 hard 키에도 `wants`를 낸다. 「+」 줄도 ②를 거친다. API 스키마 변경은 없다(`EvidenceLine.wants`는 이미 있다).
- **FE 영향**: 타입 재생성(`npm run gen:types`). 새로 선언된 상태코드(특히 409·403·429)의 화면 처리. 동작이 바뀌는 곳은 후보 게시 비작성자(403 → 404)뿐이다.

## 2026-10-02 (여섯 번째) — `PinCreateRequest.place_id` 길이 제한, 카카오 힌트 검증 (#248)

- **`PinCreateRequest.place_id`에 `maxLength: 100` 추가**(`place_name`은 이미 100). 넘기면 422 `VALIDATION_ERROR`. 검색 결과의 `place_id`를 그대로 보내는 FE는 영향 없다. 타입(`string`)은 그대로라 재생성할 것이 없다.
- 서버 동작: `place_id`가 `kakao:<숫자 1~20자리>`가 아니면 핀은 만들되(매칭은 좌표·이름으로) 카카오 ID·링크는 기록하지 않는다 — 임의 문자열이 모든 구성원의 `place_url`이 되는 것을 막는다. 이미 다른 카카오 ID가 기록된 장소는 덮어쓰지 않는다(첫 값 유지). 응답 모양 변화 없음.

## 2026-10-02 (네 번째) — `EvidenceLine.wants` 추가: 사유의 방향 (#228)

soft 키(한식·횟집·조용함 등)에 붙은 반대 사유가 추천에서 아무 효과가 없던 문제를 푼다. "한식 먹자"와 "한식 말고"가 둘 다 `cuisine_korean`이라 방향을 알 수 없었다. 규칙 전문은 `docs/constraints.md` "사유의 방향(`wants`)과 실격".

- **`EvidenceLine.wants`(선택, 신규, `boolean | null`)**: 이 특징이 있는 장소를 원하는가. `true`=원함, `false`=원하지 않음, 없거나 `null`=모름. `fact_key`가 null이면 null. hard 키(매운맛·기름짐·갑각류 등)는 방향이 고정이라 값이 있어도 쓰지 않는다.
- **FE 영향**: 타입 재생성(`npm run gen:types`). 근거 줄에 해석한 방향을 보여 준다 — 예: `wants=false` + `cuisine_korean`이면 "한식 제외", `wants=true`면 "한식 선호". 모델이 방향을 잘못 읽었을 때 사용자가 `−`로 뺄 수 있어야 한다(5-5). `wants`가 없거나 null이면 방향 표시 없이 지금처럼 보인다.
- **`EvidenceLine.fact_label`(선택, 신규, `string | null`)**: `fact_key`의 화면 표시 이름("한식", "횟집", "조용한 곳"). 서버가 내려 주므로 FE는 키→이름 표를 들지 않는다. FE는 `wants=false`면 "{fact_label} 제외", `true`면 "{fact_label} 선호"로 그린다. 서버는 `fact_key`가 있는데 이름이 없으면 안 된다(recommend 레지스트리 계약 테스트가 모든 키에 이름이 있는지 강제한다).
- 추천 결과가 바뀐다: 같은 입력이라도 "한식 말고" 사유가 있으면 한식집이 후보에서 빠진다(깔때기 "실격 조건 제거"에 세어진다).
- 구현은 llm(②가 `wants`를 낸다)과 recommend(실격·점수에 쓴다)가 한다. 그 전에는 `wants`가 항상 비어 있고 동작은 이전과 같다.

## 2026-10-02 (세 번째) — 로그인 시작 엔드포인트 `GET /auth/kakao/login` 추가, 콜백에 `state` (#128)

로그인 CSRF 방지(멘토 리뷰). 로그인 시작을 백엔드로 옮겼다 — 서버가 `state`를 만들어 서명한 httpOnly 쿠키(`kakao_oauth_state`, 경로 `/auth/kakao`, 10분)에 넣고 카카오로 보낸다. 콜백이 쿠키와 `state`를 대조하고, 성공·실패와 관계없이 쿠키를 지운다(같은 콜백 링크는 한 번만 쓸 수 있다).

- **`GET /auth/kakao/login`(신규, `security: []`)**: 302로 카카오 인가 화면 이동 + `Set-Cookie`. fetch가 아니라 **브라우저 이동**으로 부른다.
- **`GET /auth/kakao/callback`**: `state` 쿼리 추가. 쿠키와 다르거나 없거나 만료면 **401 `UNAUTHORIZED`**, `detail.reason = "invalid_state"`(JSON 봉투가 BE 주소에 그대로 보인다).
- **FE 영향(필수)**: `frontend/src/features/auth/auth.ts`의 `kakaoLoginUrl()`이 카카오 인가 URL(`client_id`·`redirect_uri` 포함)을 직접 만드는 것을 그만두고 `${VITE_API_BASE_URL}/auth/kakao/login`으로 `window.location`을 옮기게 바꾼다. `VITE_KAKAO_REST_KEY`는 로그인에 더 필요 없다(지도 SDK용 JavaScript 키와는 별개). 이 변경 전의 FE 방식은 `state`가 없어 콜백이 401로 거절한다. 목 서버(msw)는 `/auth/kakao/login`을 `/`로 302한다.
- 쿠키 호스트(`localhost`↔`127.0.0.1` 혼용) 주의는 runbook 5-3 그대로다.

## 2026-10-02 (두 번째) — 응답 객체 스키마에 `required` 선언 (멘토 리뷰 PR #152)

응답 스키마에 `required`가 없으면 핸들러가 `{}`를 돌려줘도 계약 테스트가 통과하고 생성된 FE 타입이 전부 optional이 된다. 서버가 항상 내려주는 필드를 `required`로 올렸다. 값이 없을 때 필드가 아예 빠지는 nullable 필드는 required에서 뺀다.

- **새로 required**: `Candidate`(id, rank, checks, reason, member_fulfillment, visibility, permissions), `Check`(fact_key, label, passed, confidence), `EvidenceLine`(id, author_id, text, badge, is_active, permissions), `FilterCounts`, `RecommendRun`(id, map_id, category, status, attempt_no), `Region`(전부), `User`(id, display_name), `ShortlistItem`(id, pin, added_by, permissions), `RecommendResult`(전부, `funnel` 항목 포함), `Route`(전부, `legs` 항목 포함).
- **`published_pin_id`·`visit_order`는 optional 유지**: 서버가 값이 없을 때 `null`이 아니라 필드를 생략한다(계약 테스트가 잡았다). FE는 "없거나 null"로 다룬다.
- **`Permissions`는 의도적으로 required 없음**: 맥락마다 쓰는 필드가 다르다(`can_disable`은 근거 줄 전용, `can_publish`는 후보 전용).
- **FE 영향**: 타입 재생성(`npm run gen:types`). 위 필드의 `?`와 `undefined` 방어 코드를 걷어낼 수 있다. 목 서버의 후보(`Candidate`)가 `reason`·`member_fulfillment`·`permissions` 없이 내려가던 것을 고쳤다.
- 재발 방지: `backend/integration/test_response_contract.py`가 2xx 응답 객체 스키마에 `required`가 비어 있으면 실패한다(예외는 `NO_REQUIRED_OK`에 이유와 함께).

## 2026-10-02 — `PlaceSource.provider`에 `permit`·`tourapi` 추가, 음식점 라벨 키 15개 등록 (#203)

- **`PlaceSource.provider` enum 확장(필수 필드 값 추가)**: `kakao | naver | google | permit | tourapi`. 자체 장소 DB의 장소(핀·추천 후보)에는 카카오 출처가 없으므로 `permit`(지방행정 인허가) 또는 `tourapi`(한국관광공사)가 온다. 가드레일 5(출처가 항상 붙는다)를 자체 DB 장소에서도 지키기 위한 변경이다. `url`은 출처 페이지 링크이며 없으면 생략한다.
- **FE 영향**: 타입 재생성(`npm run gen:types`). `provider`로 분기하는 코드가 있으면 새 값 2개를 처리한다. 표시 문구 예시: `permit` → "서울시 인허가 공공데이터", `tourapi` → "한국관광공사". 문구는 데이터 담당 확인 후 확정한다.
- **`fact_key` 음식점 15개 추가**(`docs/constraints.md`): `cuisine_*` 10개, `spacious`, `long_established`, `parking_available`, `vegetarian_friendly`, `franchise`. 모두 soft. API 응답의 `Check.fact_key`가 새 값을 가질 수 있다(자유 문자열이라 스키마 변경은 없다).
- `place_facts`에 `evidence`·`label_source` 컬럼 추가(DB, API 노출은 아직 없음 — 후속에서 `Check`에 근거를 실을지 결정).

## 2026-10-01 (세 번째) — 핀은 자체 DB 장소를 가리킨다: 핀 생성 규칙 변경 (#191, #53)

카카오 로컬 API 응답은 좌표·이름을 포함해 저장할 수 없다는 결정(#53)에 따라 핀을 만드는 방법과 핀 이름·좌표의 출처가 바뀐다. **스펙 문서가 먼저 바뀌었고 백엔드 구현은 아직이다** — 구현은 자체 장소 DB(#189)가 생긴 뒤 pins 이슈에서 한다. 그때까지 develop 백엔드는 이전 동작(좌표·이름을 그대로 저장)을 유지하며, 목 서버(contracts)는 새 규칙대로 동작한다.

- **핀 만들기 경로는 `source: "search"` 하나다.** `GET /places/search`(화면 표시용, 저장 안 함)의 결과를 골라 `place_id`·`place_name`·`lat`·`lng`·`category`를 그대로 `POST /maps/{mapId}/pins`로 보낸다. 서버는 이 값들을 **매칭 힌트로만** 쓰고, 같은 **자체 DB 장소**를 한 건 찾아 그 장소의 이름·좌표만 핀에 쓴다. 카카오 장소 ID와 `place_url`은 매칭된 자체 DB 장소에 함께 기록해도 된다.
- **짝이 되는 자체 DB 장소가 없으면** 핀을 만들지 않고 **422 `PLACE_NOT_SUPPORTED`**(새 코드, `docs/errors.md`)다. 화면은 "아직 지원하지 않는 장소예요"를 보여 주고 다른 장소를 고르게 한다. 요청 `category`가 장소의 분류와 다르면 422 `VALIDATION_ERROR`.
- **`source: "coordinate"`(지도 길게 눌러 찍기)와 `source: "link"`는 v1에서 받지 않는다**(422 `VALIDATION_ERROR`). 카카오 지도에서 사용자가 지정한 좌표는 저장할 수 없다. 카카오 답변이 오면 "가장 가까운 자체 DB 장소로 붙이기"를 v2에서 다시 본다.
- **`Pin.place_name`은 자체 DB 장소의 이름**이다(저장하지 않고 가져온다). `PinCreateRequest.place_name`·`place_id`·`lat`·`lng`는 저장하지 않는 매칭 힌트.
- **`PlaceSearchResult.pinnable`(선택, 신규)**: 자체 DB에 짝이 있어 핀으로 만들 수 있는가. 서버가 자체 DB를 읽기만 해서 계산한다(카카오 ID를 기록하지 않는다). false면 FE는 결과를 흐리게 보이고 선택 전에 "아직 지원하지 않는 장소예요"를 안내한다 — 검색 성공 뒤 핀 생성에서 갑자기 422가 나는 경험을 줄인다. 없으면 true로 본다.
- `PinCreateRequest`의 필수는 `category`, `place_id`, `place_name`, `lat`, `lng`(매칭 힌트 전부). `source` 기본값은 `search`.
- **`Pin.place_url`(선택, 신규)**: 매칭된 카카오 장소 페이지 링크. **외부 브라우저로 연다 — 앱 안 WebView 금지**(약관). 없으면 필드가 없다.
- 자체 DB에 없는 장소는 만들 수 없으므로 사용자가 직접 입력한 이름을 핀에 저장하는 경로는 없다. 출처 표기 의무는 없다.
- **숙소·기타 장소는 v1에서 핀으로 만들 수 없다**(2026-10-01, 데이터 담당 확인): 자체 DB는 음식점·카페·관광지만 담고 TourAPI의 숙박은 받지 않는다. 검색 결과가 숙소·기타여도 422 `PLACE_NOT_SUPPORTED`다. `Category` enum의 숙소·기타 값과 숙소 반응 불가 규칙은 그대로 둔다(스키마 호환, 숙소 데이터가 들어오는 시점에 다시 쓰인다). 숙소 핀이 전제인 기능 — 동선의 출발·도착 기준점, "숙소 기준 도보 N분" 반경 사유 — 은 v1에서는 기준점이 될 숙소 핀이 없어 동작하지 않는다(사유는 읽되 기준점을 못 찾으면 기본값 원으로 처리).
  FE: 핀 만들기 화면의 분류 선택에서 숙소·기타를 뺀다(검색 결과의 분류 제안이 숙소·기타면 "아직 지원하지 않는 장소예요").

**FE 영향**: 타입 재생성(`npm run gen:types`). 지도 길게 누르기로 핀 찍는 UI와 링크 입력은 제거하고, 검색 결과 선택 → 핀 생성만 남긴다. 생성 실패 422 `PLACE_NOT_SUPPORTED`를 처리한다. 핀 상세의 "카카오에서 보기"는 `place_url`을 새 탭/외부 브라우저로 연다. 목 서버가 이미 새 규칙대로 동작한다(검색 결과의 `kakao:mock-*` 장소만 핀이 된다).
**BE 후속**: `backend/pins`(검색 경로 매칭, 좌표·이름 저장 제거, `place_id`가 `places.id`를 가리키도록 마이그레이션) — #189 이후. 임시 상태에서 쌓인 카카오 좌표·이름은 배포 전에 로컬 DB에서 지운다.

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
