# 데이터 모델

작성 기준: `최종기획안.md`(2·5·9절) + `docs/architecture.md`
DB: PostgreSQL 17 + PostGIS(직선거리, 13절 참고). 실시간 보조: Redis(세션/멱등키, SSE 재전송 버퍼).

이 문서는 테이블 단위 스키마다. 각 모듈은 자신이 소유한 테이블만 쓰기 접근하고, 다른 모듈 테이블은 해당 모듈의 함수/API를 통해서만 읽는다(`architecture.md` 1절).

---

## auth / maps

```
users(                                -- 사람. 다른 모듈은 이 id만 가리킨다. 로그인 수단은 user_identities(#694)
  id, display_name,
  guest_invite_token null,                   -- 게스트를 만든 초대 토큰. 토큰 하나당 게스트 10명 상한(GUEST_LIMIT)을 이 열로 센다.
                                             -- 카카오 수단을 붙이면(게스트 전환) 비운다. 상한에서 빠진다
  last_seen_at timestamptz null,             -- 게스트 정리 기준: 90일 쓰지 않으면 정리 작업(#168)이 지운다. 세션을 쓸 때 하루 한 번 갱신
  created_at, deleted_at            -- 탈퇴 시 users만 soft delete. 반응·근거 줄은 hard delete, 핀은 유지하고 작성자는 '탈퇴한 구성원'으로 표시 (12절, #155)
  sessions_valid_after timestamptz null   -- 로그아웃 시각. 이 시각 이전(같은 초 포함)에 발급된 세션 토큰은 무효, NULL이면 전부 유효 (#129)
)

user_identities(                      -- 로그인 수단(#694, 2026-10-24). 사람(users)과 나눈다
  id uuid, user_id → users.id, provider('kakao'), provider_user_id, created_at
  unique(provider, provider_user_id)    -- 카카오 계정 하나는 사람 하나에만
  unique(user_id, provider)             -- 한 사람에 카카오는 하나
)
-- 게스트(v2 #472) = 로그인 수단이 없는 사용자. 세션 쿠키로만 들어온다. is_guest는 저장하지 않고 "수단이 하나도 없는가"로
--   계산한다(CurrentUser.is_guest, GET /auth/me). 저장하면 수단을 붙일 때 함께 고치는 것을 빠뜨릴 수 있다.
-- 탈퇴(deleted_at)해도 수단은 지우지 않는다. 같은 카카오 계정의 재로그인을 "탈퇴한 계정"으로 막는 근거다(#409).
-- 예전 users.provider, provider_user_id, is_guest는 이 리비전에서 지운다(카카오 사용자는 user_identities로 옮긴다).

maps(
  id, title, start_date, end_date, member_count_expected,
  region_label NULL, region_center geography(Point) NULL,   -- 9/28 #22 변경(PR #132, 루트 검증
                                                             -- 후 승인): 지역 검색(선택). 둘 다
                                                             -- 있거나 둘 다 없음
  created_by, created_at,              -- created_by는 "만든 사람" 기록일 뿐 방장 판단에 쓰지 않는다(#369, 방장 정본은 memberships.role)
  deleted_at timestamptz null          -- #369: 방장이 삭제하면 찍는다(soft delete). 찍히면 모든 조회 경로에서 없는 지도(404)로 보인다.
                                       --   #431(2026-10-10): 삭제한 지 30일이 지나면 정리 작업(`python -m maps.purge`)이 지도와 딸린 데이터를 실제로 지운다. v1에는 복구 기능이 없다.
                                       --   → docs/architecture.md 「지도 삭제와 정리」
)
  CHECK (end_date >= start_date)   -- 9/4 결정 #22: 여행 제목 + 시작일·종료일. day_count는 폐기
  CHECK ((region_label IS NULL) = (region_center IS NULL))

memberships(
  id, map_id, user_id, role('member'|'owner'),   -- authz 참고. color는 9/4 결정 #26으로 폐기(구성원 구분에 색 불필요)
                                                 -- #369: role이 방장 판단의 정본이다. 방장이 나가면 joined_at이 가장 빠른
                                                 --   구성원(탈퇴자 제외, 같으면 id 순)에게 위임된다
  joined_at
)
  unique(map_id, user_id)
  unique(map_id) where role = 'owner'   -- #369: 지도당 방장은 최대 1명. 위임은 한 트랜잭션에서 강등 후 승격
  -- 나가기(#369)는 이 행을 지운다. 다시 초대를 수락하면 새 행과 새 joined_at이 생겨 순서 맨 뒤로 간다.
  -- 탈퇴자의 행은 핀 작성자 표시용으로 남는다(#245).

invites(
  token, map_id, created_by, expires_at, used_count,
  created_at, revoked_at            -- revoked_at: 방장이 끈 시각(NULL이면 켜짐, #467). map_id 인덱스
)
```

---

## pins (5-1, 5-2, 4절)

```
pins(
  id, map_id, category('음식점'|'카페'|'숙소'|'관광지'|'기타'),  -- 정의는 backend/common/categories.py(#280). v1 핀은 음식점·카페·관광지만
  kind('일반'|'AI추천'|'확정'),        -- 확정이 나머지 둘을 덮어쓴다(5-2)
  origin('direct'|'ai'),               -- kind와 별개. 원래 태생은 안 바뀐다(4절: 반대 많아도 모양 불변)
  place_id null references places(id), -- 2026-10-01 결정(#191): 자체 DB 핀(source='db')은 자체 DB 장소를 가리킨다.
                                        -- 이름은 places.name에서 가져온다 — 핀에 따로 저장하지 않는다(place_name 컬럼은 없앤다).
                                        -- 카카오 응답의 이름·좌표는 저장하지 않는다. #382: source='live'(실시간 핀)는 place_id가 NULL이다.
  source('db'|'live'),                 -- #382. live = 자체 DB에 없는 장소를 사람이 남긴 핀. AI 핀(origin='ai')은 항상 db
  kakao_place_id null,                 -- #382 live만. 저장이 허용된 유일한 카카오 값. 화면이 위치를 다시 찾는 열쇠
  search_query null,                   -- #382 live만. 사용자가 친 검색어(사용자 입력). 화면이 이 검색어로 카카오 키워드 검색을 다시 한다
  memo null,                           -- #382 live만. 사용자가 남긴 한마디(최대 200자)
  geom null geography(Point,4326),     -- 매칭된 places.geom의 복사(자체 데이터). 사용자가 카카오 지도에서 지정한 좌표와 카카오 응답 좌표는 저장하지 않는다. live 핀은 NULL
  visibility('public'|'private'),      -- v1은 항상 public. 이 값으로 분기하지 않는다(#273). 비공개 AI 후보는 pins가 아니라 candidates 행이고, 게시할 때 처음부터 public 핀으로 만든다. 칸은 마이그레이션 때문에 남기고, Pin 스키마를 크게 바꿀 때 같이 지운다
  source_run_id null,                  -- #57 결정: recommend_runs.id를 게시 시점에 한 번만
                                        -- 써넣는 불투명 참조값(추적·표시용). FK 제약은 걸지 않고
                                        -- pins는 이 값을 절대 다시 읽어 recommend를 조회하지
                                        -- 않는다("모듈 간 접근은 함수/API로만" 원칙은 실시간
                                        -- 조회 금지가 핵심이지, 게시 시점 1회성 값 복사를 막지
                                        -- 않는다 — candidates.lat/lng 비정규화와 같은 논리).
  checks jsonb null,                   -- #57 결정: candidate.checks를 게시 시점에 복사(가드레일
                                        -- 5, 게시 후에도 조건별 충족 체크가 유지돼야 함). run·
                                        -- candidate가 나중에 지워지거나 바뀌어도 이 값은 안 바뀐다.
  created_by, created_at, deleted_at
)
  unique(map_id, place_id) where deleted_at is null   -- 중복 핀 판정(가드레일 6). 판정 기준은 #33(보류)에서 별도 확정
  unique(map_id, kakao_place_id) where deleted_at is null and kakao_place_id is not null   -- #382 live 핀 중복
  check (source = 'db' and place_id is not null and geom is not null
      or source = 'live' and place_id is null and geom is null and kakao_place_id is not null and search_query is not null)

reactions(
  id, pin_id, user_id, type('like'|'against'),  -- ♥/🚫. '?'미확인은 행 없음으로 표현. 2026-10-07(#360) △ 조율 필요(neutral)를 없앴다 — 마이그레이션이 neutral 행을 지운다
  reason_text, reason_chip_ids jsonb,   -- 반대는 reason 필수(가드레일 3). 숙소 핀엔 행이 생기지 않는다(#154). 작성자 탈퇴 시 삭제(#155)
  created_at, updated_at
)
  unique(pin_id, user_id)
```

`kind`가 바뀌는 유일한 경로는 확정 리스트 추가/제외(5-3)다. `origin`은 불변이며 "이미 제안·거절된 곳" 판정(가드레일 6)과 무관하다 — 그건 `recommend.exclusions`가 따로 갖는다.
`kind='확정'`은 `shortlist`가 `pins.api.mark_confirmed()`/`unmark_confirmed()`를 통해서만
바꾼다. 확정 제외 시 되돌릴 값은 저장하지 않고 `origin`에서 파생한다
(`pins/core.py::kind_after_unconfirm`: `origin='ai'` → `'AI추천'`, `origin='direct'` → `'일반'`).

---

## shortlist

```
shortlist_items(
  id, map_id, pin_id, added_by, added_at,
  visit_order int null                 -- #30 수동 정렬(허용 확정). 동선(routes)과는 무관한
                                        -- 별개 컬럼이다(최종기획안.md 9/4 결정 "visit_order 수동
                                        -- 정렬 허용, 동선과는 무관") — 플레인 리스트 화면의
                                        -- 드래그 순서일 뿐, routes 재계산이 이 값을 읽거나 쓰지
                                        -- 않는다.
)
  unique(map_id, pin_id)

routes(
  id, map_id,
  region_label,                        -- 확정 핀이 여러 지역에 걸치면 지역별로 한 행씩(api-spec.yaml Route)
  ordered_pin_ids jsonb,                -- pin_id 배열, 계산된 순서 그대로
  total_distance_m,
  legs jsonb,                          -- [{from_pin_id, to_pin_id, distance_m, approx_minutes}]
  computed_at
)
  unique(map_id, region_label)          -- 동시 POST 재계산 시 같은 지역 행이 중복 적재되는 것을 막는다
  index(map_id)
  -- GET은 그 map_id의 모든 행(=가장 최근 POST 한 번이 만든 지역별 결과 전부)을 그대로 반환한다
  -- — "마지막 결과"란 "행 1개"가 아니라 "가장 최근 계산 배치"라는 뜻이다. 지역이 여러 개면
  -- 여러 행이 그대로 여러 Route 원소가 된다. 재계산 안 함(GET은 절대 재계산하지 않는다).
  --
  -- POST가 재계산할 때마다 그 map_id의 기존 행을 전부 지우고 새로 쓴다 — 이전 계산 결과는
  -- 최신 결과로 완전히 대체되는 것이 맞고(동선은 "그 시점의 확정 리스트 스냅샷"이지 누적
  -- 이력이 아니다), 부분 갱신할 이유가 없다. DELETE와 INSERT는 반드시 같은 요청의 같은
  -- 트랜잭션 안에서 실행한다(common.database.get_db_session 기본 동작 — 커밋 전까지 다른
  -- 요청에는 삭제 전 상태가 그대로 보이므로 GET이 빈 배열을 보는 순간이 생기지 않는다).
  -- 확정 핀이 0개면 행을 만들지 않는다(빈 배열로 응답). 1개면 legs는 빈 배열, total_distance_m
  -- 은 0인 한 행을 만든다(에러 아님).
```

쓰기 소유: `shortlist`. `pins.kind='확정'` 갱신은 `shortlist`가 `pins.api.mark_confirmed()`를
통해서만 한다(위 규칙 유지). 거리 계산(최근접 이웃, 원 겹침 판정)은 `common/geo.py`의 공용
유틸을 쓴다 — `recommend`의 반경 판정(5-6-1)도 같은 종류의 계산이 필요해서 미리 공용화한다
(`backend/common/CLAUDE.md`가 이미 "PostGIS 좌표 유틸"을 common의 책임으로 못박아둠).

---

## places / place_facts (architecture.md 2절 — 자체 장소 DB)

> **🚨 이 스키마는 이용약관 검토가 끝나기 전까지 잠정안이다.** `places` 테이블이 `name`·`address`·`phone`·`geom`을 영구 저장하도록 설계돼 있는데, 카카오 로컬 API 등은 결과의 영구 저장 자체를 금지할 수 있다는 정황이 나왔다 — [#53](https://github.com/kakaotechcampus-4/ktc4-chungnam-2/issues/53) 참고. `source_id`/`place_url` 외 필드의 실제 수집·저장 구현은 이 이슈가 풀린 뒤에 시작한다.

```
places(
  id,
  source('permit'|'tourapi'),          -- permit = 지방행정 인허가 공공데이터(음식점·카페), tourapi = 한국관광공사 TourAPI(관광지·문화시설·레포츠·시장, contenttypeid 12·14·28·38 → 분류 관광지)
  source_id,                            -- 그 데이터셋의 관리번호/콘텐츠 ID
  name, category('음식점'|'카페'|'관광지'), address, phone,
  geom geography(Point,4326),          -- 인허가 좌표계가 위경도가 아니면 변환해 넣는다. 좌표가 없는 행은 적재하지 않는다
  status('open'|'closed'),             -- 인허가 영업 상태. closed는 검색·추천에서 제외
  curated boolean not null default false,
                                        -- 정예(사람이 직접 조사·납품한 데이터)인가(2026-10-16). `--authoritative` 적재가 켠다.
                                        -- 이름·분류·라벨을 인허가 커버리지가 덮지 못하게 하고 can_recommend 판정의 기준이다.
                                        -- 한 번 true가 되면 커버리지 적재가 끄지 않는다. 처음 채울 때는 "출처(label_source)가 NULL인
                                        -- 라벨 행을 가진 장소 = 정예"로 되메운다(places/for_Root.md #can_recommend 조사 결과).
  can_recommend boolean not null default false,
                                        -- AI 추천 후보 풀에 들어가도 되는 장소인가(2026-10-15 결정, 구현은 places).
                                        -- 직접 찍은 핀·검색·링크에는 영향이 없다 — 추천 후보를 고를 때만 쓴다.
                                        -- 규칙(재계산 가능한 값이다, 사람이 손으로 정하지 않는다):
                                        --   정예 행(curated=true)만 true다. 정예가 아닌 데이터(인허가 커버리지 등)는 지도에 핀을 꽂을 수 있는 최소 정보일 뿐 추천 후보가 아니다(원칙, 2026-10-24).
                                        --   라벨 수 임계는 2026-10-24에 폐기했다 — 비정예 장소의 확정 라벨이 전부 인허가에서 자동으로
                                        --   나온 값(cuisine_* 10개·spacious·franchise 등)이라 품질 신호가 아님을 실측으로 확인했다(#681-1).
                                        -- 정예가 늘면(재적재) places의 재계산 스크립트로 다시 계산한다.
  kakao_place_id null, kakao_place_url null, kakao_matched_at null,
                                        -- 사용자가 검색해서 고를 때 한 건씩 매칭한 결과. 허용 범위: 카카오 장소 ID·URL·확인 일자.
                                        -- 카카오 응답의 이름·주소·좌표는 저장하지 않는다(#53)
  created_at, updated_at
)
  unique(source, source_id)

place_facts(
  place_id references places(id),
  fact_key,                             -- 'spicy_focused' | 'cuisine_korean' | 'parking_available' | ... (price_bucket은 #423, contains_shellfish는 #425에서 뺐다)
                                         -- constraints.md의 라벨링 대상만 저장: 실격 6개 + 선호 조건
                                         -- is_open/within_radius는 코드 판정이라 여기 없다(실시간 조회·좌표 계산)
  value,                                 -- boolean/enum, jsonb로 통일 저장
  confidence('known'|'unknown'),        -- D4: unknown_policy는 constraints.md 참고
  source_layer(1|2|3),                  -- architecture.md 3층 모델
  evidence null,                        -- 라벨의 근거 원문(예: "인허가 업태 '일식'") — 가드레일 5의 "이유·출처"에 쓴다 (#203)
  label_source null,                    -- 근거의 종류(license_business_type, license_date, 모범음식점 …)
  model_version null,                   -- source_layer=3일 때만
  labeled_at
)
  primary key(place_id, fact_key)

place_hours(                            -- v2 #690(2026-10-24): 영업시간·휴무일. 칸이 없으면 **행이 없다 = 모름**(지어내지 않는다)
  place_id primary key references places(id) on delete cascade,
  hours jsonb null,                     -- {"월": [["11:00","21:00"]], "화": [["12:30","15:00"],["17:00","22:00"]], "일": []} — 요일 키 7개(월~일),
                                         --   값은 [여는 시각, 닫는 시각] 목록(브레이크타임이면 구간 여러 개), 빈 목록 = 그 요일 휴무,
                                         --   자정을 넘기면 24를 더한다("26:00" = 다음 날 02:00), 상시 개방 = [["00:00","24:00"]].
                                         --   hours가 있으면 7일을 다 아는 경우다. NULL이면 모름(closed_days만 있을 수 있다)
  closed_days text[] null,              -- 매주 쉬는 요일("월","화"…). [] = 매일 영업(연중무휴), NULL = 모름. hours가 있으면 hours에서 빈 목록인 요일과 같다
  closed_note text null,                -- 요일로 못 담는 휴무 원문(예: "1월 1일 / 설·추석 당일", "공연별 상이") — 표시용, 판단에 쓰지 않는다
  hours_note text null,                 -- 영업시간 원문(계절별 운영 등은 가장 긴 계절 기준으로 hours에 넣고 원문은 여기) — 표시용
  updated_at timestamptz not null default now()
)
```

> **영업시간·휴무일 (v2, #690)** — 데이터 담당 공유본(2026-10-21)의 정예 라벨 JSON `info.hours`·`info.closed_days`·`closed_note`·`hours_note`(음식점 `rest_`·카페 `cafe_` 접두어, 지역 관광지 포함)와 서울 관광지 별도 파일 `tourist_seoul_closed_days.json`(`source_id`=contentid)에서 적재한다. 출처는 구글 지도 영업시간 + TourAPI 이용시간·쉬는날 + 모델로 형식 변환한 문장(데이터 담당 소관)이라 카카오 응답이 아니다 — 저장해도 된다(#53). 라벨 키(`closed_mon`…)로는 시간 구간을 못 담고 `places`에 칸을 늘리면 비대해져 별도 테이블로 둔다. 인허가 커버리지 라벨에는 `info`가 없어 행이 없다(모름). 마이그레이션은 구현 PR이 그때의 head 다음 번호로 만든다. 적재는 멱등(같은 장소는 갱신)이고 파일에 칸이 없는 장소의 기존 행은 지우지 않는다.

> **2026-10-01(#53) — `places`는 자체 DB다.** 카카오 로컬 API 응답(좌표·이름·주소 포함)은 어떤 형태로도 저장하지 않으므로 이 표의 이름·좌표는 인허가 공공데이터와 TourAPI에서만 온다(v1 서울만). 이전 설계의 `source('kakao'|'google'|'naver')`와 `last_synced_at`은 없앴다. 자체 DB는 음식점·카페·관광지만 담는다(TourAPI의 숙박은 받지 않는다, 2026-10-01) — 숙소·기타 장소는 `places`에 없으므로 v1에서 핀으로 만들 수 없다(`pins.category`의 숙소·기타 값은 스키마 호환으로 남긴다). 핀이 `places.id`를 가리키도록 바꾸는 `pins` 변경은 #195에서 한다.
>
> `place_facts`의 v1 라벨은 데이터 담당의 라벨 파일에서 적재한다(`model_version`은 모델 라벨링을 하는 v2부터 채운다). 값이 비어 있으면 `confidence=unknown`.

> **라벨 파일 형식 (v1, 데이터 담당 → `place_facts` 적재, #189)** — UTF-8 CSV, 한 줄이 (장소, `fact_key`) 하나.
>
> | 열 | 필수 | 설명 |
> |---|---|---|
> | `source` | O | `permit` 또는 `tourapi` (`places.source`) |
> | `source_id` | O | 그 데이터셋의 관리번호/콘텐츠 ID (`places.source_id`) — `(source, source_id)`로 장소를 찾는다 |
> | `fact_key` | O | `docs/constraints.md`에 있는 키만. 모르는 키가 있으면 적재 스크립트가 그 줄을 건너뛰고 건수를 보고한다 |
> | `value` | △ | `true`/`false`. `confidence=unknown`이면 비운다. 등록되지 않은 키(예: #423에서 뺀 `price_bucket`)는 적재 스크립트가 건너뛴다 |
> | `confidence` | O | `known` 또는 `unknown` — 확인하지 않은 값은 `unknown` |
> | `labeled_at` | X | ISO 날짜. 없으면 적재 시각 |
> | `evidence` | X | 근거 원문(`place_facts.evidence`). 있으면 그대로 저장한다 |
> | `label_source` | X | 근거의 종류(`place_facts.label_source`) |
>
> **음식점 납품본은 JSON이다**(`restaurant_seoul_curated_labels.json`, #203): 장소마다 `place_id`(`rest_<인허가 관리번호>`)와 `labels{fact_key: {value, evidence, source}}`가 있다. 적재 스크립트가 이를 위 CSV 형식으로 변환해 읽는다(`place_id`에서 `rest_`를 떼면 `source_id`, `source`는 `permit`). `value`가 문자열 `"true"/"false"/"unknown"`으로 온다. `unknown`은 `confidence=unknown`으로 옮긴다.
>
> 같은 `(source, source_id, fact_key)`가 여럿이면 마지막 줄이 이긴다(경고). 적재는 멱등 upsert(`primary key(place_id, fact_key)`)라 파일을 다시 올려도 안전하다. 파일에 없는 장소·키는 건드리지 않는다. 원본 가격 숫자는 이 파일에 넣지 않는다(가격 라벨은 #423에서 뺐다).

**`place_facts`는 캐시가 아니다.** TTL로 만료시키지 않는다 — 원본이 따로 없는 1차 데이터이기 때문이다(멘토: "자체 DB 구축이 곧 해자"). 가게 정보가 실제로 바뀌었다고 판단되면 `labeled_at` 기준으로 재라벨링 잡을 새로 돌려 **덮어쓴다**(버전 갱신이지 캐시 무효화가 아니다).

압축된 판정값만 저장하고 원본 숫자(가격 등)는 저장하지 않는다(architecture.md 2절, 차원 압축). 가격 라벨은 v1에서 뺐다(#423).

---

## seeding (신규, architecture.md 3절)

```
seeding_jobs(
  id, map_id null,                      -- null이면 발표용 사전 선점 배치
  region_geom geography, region_label,
  status('queued'|'running'|'done'|'failed'),
  triggered_by('map_created'|'manual'),
  created_at, finished_at
)
```

---

## recommend (3절, 5-5~5-6-1)

> `recommend_runs`·`candidates`는 **서버 DB 영속 저장**으로 확정됐다(#43, 9/4 결정) — "비공개 AI 추천 후보는 시간이 지나도, 재접속해도 사라지지 않는다. 게시 또는 재추천으로만 대체된다."

```
recommend_runs(
  id, map_id, category, requested_by, status,
  attempt_no,                           -- #31 확정(2026-09-22, 황준영·itsmedoyun 합의): 개인
                                         -- (requested_by) 단위로 집계, 카테고리 구분 없음(그
                                         -- 사람이 이 지도에서 만든 모든 run이 카테고리 무관하게
                                         -- 한 카운터를 공유), 상한 10회(3→5→10회, 2026-10-15: 지도 안에서 구성원 각자). 한
                                         -- 사람이 상한에 도달해도 다른 사람의 추천 시도에는
                                         -- 영향 없음.
  last_funnel jsonb null,               -- #108 추가: GET /runs/{id}/result가 매번 재계산하지
                                         -- 않도록 마지막 execute/widen/retry의 깔때기 표를
                                         -- 저장해둔다. 파생값이라 정본은 항상 마지막 실행 결과.
  created_at
)

evidence_lines(
  id, run_id, author_id,                -- "자기가 쓴 것만 뺄 수 있다"(5-5) — author_id로 권한 판정
  source('reaction'|'manual'),
  text, chip_id null,
  badge('required'|'preferred'|'reference'),  -- 꼭/선호/참고
  fact_key null,                        -- 실격/선호 조건에 매핑되면 채움
                                         --   한 행은 조건 하나다. 사유 글 하나에 조건이 여럿이면 같은 text로 여러 행이 된다(#419). 칩은 칩마다 한 행(#412)
  wants boolean null,                   -- 방향(#228): 이 특징이 있는 장소를 원하는가. true=원함, false=원하지 않음, null=모름.
                                         --   fact_key가 null이면 null. hard 키는 방향이 고정(있으면 실격)이라 wants를 보지 않는다. docs/constraints.md "사유의 방향"
  circle_anchor_pin_id null, circle_radius_m null,  -- 반경 사유(5-6-1)
  is_active boolean default true,       -- '-'로 뺀 상태
  created_at,
  seq bigint generated always as identity  -- 넣은 순서(#428). 근거 줄은 ORDER BY created_at, seq로 읽는다.
                                         --   created_at은 트랜잭션 시작 시각(now())이라 run 생성 때 한 번에 넣은 줄끼리 같다 — seq가 없으면
                                         --   "한 반응의 글 줄 다음에 칩 줄"(#412, #419) 같은 순서가 보장되지 않는다. 응답에는 넣지 않는다
)

regions(
  id, run_id, signature,                -- 5-6-1 겹침 판정 서명. 무효화 규칙: signature 재계산 시 값이 바뀌면 재확인
  label,                                 -- #108 확정: places가 없어 리버스 지오코딩(장소명 조회)이
                                         -- 안 되므로 "N번째 지역" 같은 라벨을 여기서 직접 만들어 저장
  center_lat, center_lng, radius_m,     -- #108 확정: geom geography 대신 병합된 원(중심+반경)을
                                         -- 평범한 컬럼으로 저장 — candidates.lat/lng와 같은 차원
                                         -- 압축 논리. 실제 PostGIS 연산이 필요해지면(예: 핀-지역
                                         -- 포함 판정을 DB 레벨로 옮길 때) geom 컬럼을 추가하는
                                         -- 별도 마이그레이션으로 되돌린다.
  confirmed boolean, confirmed_at
)

candidates(
  id, run_id, place_id, region_id,
  lat, lng,                             -- places가 아직 없어 온디맨드 조회 불가 — 후보 생성
                                         -- 시점에 좌표를 직접 들고 있는다(PR #71, pins가
                                         -- 자기 geom을 따로 갖는 것과 같은 이유). places 붙으면
                                         -- place_id로 조회하는 방향으로 재검토
  rank, checks jsonb,                   -- 조건별 충족 체크(가드레일 5)
  member_fulfillment jsonb,
  published_pin_id null,                -- 5-5-1 게시 후 연결
  created_at
)
  -- 게시(publish) 구현 시 주의할 것(Antigravity 검수, #64/#57 처리 중 발견 — 아직 recommend가
  -- 없어 지금 고치는 게 아니라 여기 남겨둔다):
  -- 1. can_publish는 requested_by 본인만이 아니라 published_pin_id is null(아직 미게시)도
  --    같이 봐야 한다 — 안 그러면 이미 게시된 후보도 게시 버튼이 계속 활성화된다.
  -- 2. 게시는 pins.unique(map_id, place_id) where deleted_at is null 제약과 만난다 — 같은
  --    장소에 이미 핀(수동이든 이전 게시든)이 있으면 게시 INSERT가 충돌한다. 409로 처리할지
  --    기존 핀과 병합할지 정해야 한다.
  -- 3. pins.source_run_id/checks는 write-once다 — 핀 수정 엔드포인트가 생기면 그 요청
  --    스키마에서 반드시 제외한다(클라이언트가 덮어쓸 수 없게).

exclusions(
  map_id, category, place_id, reason('proposed'|'dismissed'),
  run_id, requested_by, created_at
)
  unique(map_id, requested_by, place_id)  -- #42 확정: 개인 단위라 (map_id, place_id)만으로는
                                           -- 부족하다 — 같은 곳을 여러 명이 각자 거절할 수 있다
  -- "다시 추천 받기" 시 현재 뜬 후보 전체가 이 사람(requested_by) 몫으로 여기 들어간다(3절,
  -- 루프가 닫힌다). #42 확정(2026-09-22, 황준영·itsmedoyun 합의): 개인 단위 — A가 거절한
  -- 곳도 B의 추천에는 그대로 뜬다. 조회 시 반드시 requested_by = 현재 사용자로 필터링한다
  -- (map_id만으로 걸러진 예전 설계를 그대로 두면 다른 사람의 거절이 새어 들어간다).
```

---

## ads (추천 탭 광고, docs/ads.md 6절, #642)

> 광고는 자체 DB(places)에 이미 있는 장소만 가리킨다. ads 모듈이 두 테이블을 소유하고, places는 `places.api`로만 읽는다(#113). 집계에는 user_id, map_id를 넣지 않는다.

```
ads(
  id uuid primary key,
  place_id text not null,              -- places.id. 모듈 경계라 FK 없음(등록 스크립트가 존재와 status=open을 검증)
  starts_at timestamptz not null,
  ends_at timestamptz not null,        -- 이 시각은 포함하지 않는다
  active boolean not null default true,-- 기간과 별개로 즉시 내리는 스위치
  memo text null,                      -- 광고주, 계약 메모(내부용, 응답에 내보내지 않음)
  created_at, updated_at
)
  check (starts_at < ends_at)
  unique(place_id) where active        -- 같은 장소에 active 광고는 하나(제안)

ad_daily_stats(
  ad_id uuid not null references ads(id),
  stat_date date not null,             -- Asia/Seoul 기준 날짜
  served_count integer not null default 0,   -- 광고 조회 응답에 실린 횟수(화면 노출이 아니다, docs/ads.md 9절)
  click_count integer not null default 0,
  primary key(ad_id, stat_date)
)
  -- 증가는 INSERT ... ON CONFLICT (ad_id, stat_date) DO UPDATE SET 칸 = 칸 + 1
```

---

## agent (v2 계획 보조 에이전트, docs/agent-v2.md 13절, #510)

> v2. 계약만 먼저 올렸고 마이그레이션은 agent 모듈 M0에서 지금 head 다음 번호로 만든다. agent는 이 7개 테이블만 쓰고, 다른 모듈 데이터는 `<module>/api.py`로만 읽는다.
> `map_id`는 다른 모듈처럼 문자열이고 FK를 걸지 않는다. 지도 정리(#431)는 `agent.api.purge_map_data`, 탈퇴(#155)는 `agent.api.delete_by_user`가 맡는다.
> **agent 테이블에는 사유 원문을 저장하지 않는다**(2026-10-15). 사유는 `reaction_id`로만 가리키고, 인용 문장은 응답과 이벤트를 만들 때 pins에서 읽어 렌더한다. 반응이 지워지면 인용도 사라진다(docs/agent-v2.md 2절 13번).

```
agent_settings(                       -- 지도별 모드. 행이 없으면 켜짐(기본값)
  map_id primary key, enabled boolean, updated_by, updated_at
)

agent_cursors(                        -- 관찰 흐름만 쓴다. 지도별 책갈피와 다음 점검 시각, 중복 실행 방지 자리표
  map_id primary key,
  last_seen_seq bigint default 0,     -- 관찰 때 본 가장 큰 event_log seq(구멍은 추적하지 않는다, agent-v2.md 12.5)
  last_observed_at null, next_check_at null, lease_until null
                                      -- gap_seq는 0030에서 지웠다(#515)
)

agent_runs(                           -- 관찰 한 번의 기록. 침묵으로 끝나도 남긴다. 30일 보존
  id uuid, map_id, started_at, finished_at null,
  trigger('activity'|'time'|'summary'|'run_advice'),
  snapshot_at null, snapshot_seq null,
  signals jsonb, blocked jsonb, priority jsonb null,
  policy_version null, prompt_version null, model null, used_model boolean,
  tool_calls jsonb,                   -- 도구 입력과 결과. 사유 글은 reaction_id와 글자 수로 바꿔 남긴다
  verification jsonb null, tokens_in, tokens_out,
  outcome('no_signal'|'blocked'|'silent'|'unknown'|'invalid_schema'|'invalid_claims'|'model_failed'|'stale'
          |'suggested'|'summarized'|'advised'|'trip_ended'|'map_deleted'),
  outcome_detail jsonb null
)
  index(map_id, started_at)

agent_suggestions(                    -- 바텀시트의 지도 제안
  id uuid, map_id, run_id null references agent_runs on delete set null,
  diagnosis('stall'|'split'|'no_reaction'|'category_gap'), category null, pin_id null,
  fingerprint, evidence_hash,         -- 중복 금지(유형+카테고리+근거 id), 상태 재확인(근거 id+반응 종류+updated_at)
  title, claims jsonb, analysis jsonb null, advice jsonb, actions jsonb,   -- 슬롯 문장과 검증 통과 claim(quote는 reaction_id, 인용 범위, 범위의 다이제스트만. 원문 없음, #717). 렌더는 응답 때 조각으로
  status('active'|'accepted'|'dismissed'|'expired'|'superseded'),
  shadow boolean default false,       -- true면 저장만 하고 화면과 이벤트에 내지 않는다
  created_at, expires_at,             -- 24시간
  resolved_by null,                   -- 기록만. 화면과 이벤트에 싣지 않는다
  resolved_at null, resolved_action jsonb null, decided_within_24h boolean null
)
  unique(map_id) where status = 'active'   -- 지도당 활성 제안 하나
  index(map_id, fingerprint)

agent_suggestion_views(               -- 사용자별 열람. 버튼의 점(has_unseen)
  suggestion_id references agent_suggestions on delete cascade, user_id, viewed_at,
  primary key(suggestion_id, user_id)
)

agent_reason_summaries(               -- 우리 조건 요약. 카테고리마다 최신본 하나를 덮어쓴다
  map_id, category, summary jsonb,    -- api-spec AgentSummary의 다섯 칸(키, 개수, 서버 문구)과 근거 reaction_id. 사유 원문 없음
  based_on_reaction_count, run_id null, updated_at,
  primary key(map_id, category)
)

agent_run_advice(                     -- 추천 막힘 조언. run당 1행, 조언이 없어도 빈 값으로 저장해 다시 만들지 않는다
  run_id primary key,                 -- recommend_runs.id. 모듈 경계라 FK 없음
  map_id, kind null, claims jsonb, advice jsonb, actions jsonb, agent_run_id null, created_at
)
```

---

## agent_course_runs (AI 코스 짜기, #334 — 팀 결정 #580 전 브랜치 초안, 마이그레이션 0037)

> 동선 에이전트(`backend/agent/course/`)가 쓰는 테이블 1개. `map_id`, `requested_by`는 문자열이고 FK가 없다. run은 요청자 본인 것이다(가드레일 1).
> **장소 이름과 좌표는 저장하지 않는다.** 핀은 `pin_id`로만 가리킨다(화면 문장에 들어간 이름은 코드가 렌더한 문장 안에만 있다). 사유 원문도 없다 —
> 요청 한 줄(`input.request_text`)은 요청자가 이 run을 위해 쓴 글이라 run 행에만 둔다. 지도 정리와 탈퇴 정리는 `agent.course.api`(`purge_map_data`, `delete_by_user`)가
> 맡는다 — `maps/purge.py`의 PURGE_STEPS와 `withdraw_user`에 연결돼 있다. 질문에 답을 받지 않아 waiting_input 상태와 답 칸이 없다.

```
agent_course_runs(
  id uuid, map_id, requested_by,
  status('queued'|'running'|'done'|'failed'),
  outcome null('solved'|'solved_with_checks'|'unresolved'|'timeout'),    -- done일 때만
  failure_code null('INTERRUPTED'|'ENGINE_ERROR'),                       -- failed일 때만
  input jsonb,                        -- {request_text, member_constraints:[{kind:'daily_walk_max', value, day}]}
  snapshot_at, snapshot_pin_ids jsonb,-- 요청 때 확정 리스트의 핀 id. 지금과 다르면 응답의 stale=true
  goals jsonb, unmatched jsonb,       -- [{id, kind, label, met}], 요청 원문 조각
  excluded jsonb,                     -- [{pin_id, reason('NO_COORDINATES'|'OVER_LIMIT'), text}]
  steps jsonb,                        -- [{stage, role, by, by_detail, text}] 작업 기록(끝난 뒤 한꺼번에 채운다)
  days jsonb,                         -- [{date, slots:[{pin_id, order, needs_check}], legs:[{from_pin_id, to_pin_id, mode(walk|transit), approx_minutes}]}]
  violations jsonb, checks jsonb,     -- [{kind, text}], [{pin_id, text}]
  model null, prompt_version null, model_turns, tokens_in, tokens_out,
  created_at, finished_at null
)
index ix_agent_course_runs_map_user (map_id, requested_by, created_at)
index ix_agent_course_runs_user_created (requested_by, created_at)       -- 하루 상한(5회, KST 자정) 집계
unique uq_agent_course_runs_active (map_id, requested_by) where status in ('queued','running')   -- 내 진행 중 run은 지도당 하나 → 409 COURSE_IN_PROGRESS
```

- 진행 중으로 15분 넘게 남은 run은 다음 요청이 `failed(INTERRUPTED)`로 끝낸다. 서버가 시작할 때도 진행 중인 run을 모두 같은 값으로 끝낸다(인스턴스 하나 전제, #168).
- 영업시간 칸이 places에 아직 없어(#580 6번) 지금은 모든 장소가 「확인 필요」(`checks`)다.

---

## notifications / feedback (v2, #470, #10)

> v2. 계약만 먼저 올렸고 마이그레이션은 구현 PR이 그때의 head 다음 번호로 만든다(번호를 문서에 못 박지 않는다 — agent·maps 마이그레이션과 겹친다). 이슈 본문의 `0026`은 옛 초안이다.
> notifications는 이 테이블들만 쓴다. 다른 모듈은 `notifications/api.py`의 `notify(db, ...)`만 부르고, **이벤트를 발행하는 같은 트랜잭션에서** 호출한다(event_log는 지도 단위이고 읽음 상태가 없어 알림함으로 못 쓴다).

```
notifications(                        -- 사용자별 알림함. 수신자마다 한 행
  id, user_id, map_id,                -- map_id는 FK 없음(지도가 삭제돼도 알림은 남는다)
  type,                               -- NotificationType 5종(api-spec)
  map_title,                          -- 만들 때의 제목 스냅샷
  pin_id nullable,                    -- pin_reaction·my_ai_pin_published만. FK 없음
  message,                            -- 서버가 만든 문장. 반대 사유·메모는 넣지 않는다
  created_at, read_at nullable,
  index (user_id, created_at desc), index (user_id) where read_at is null
)
notification_prefs(                   -- 행이 없으면 켜짐(기본값)
  user_id, type, enabled, primary key (user_id, type)
)
feedback(                             -- 서비스 피드백. 저장만 한다
  id, user_id nullable,               -- 탈퇴하면 NULL로 끊고 내용은 남긴다
  category,                           -- bug | idea | other
  message,                            -- 1~1000자, 앞뒤 공백 제거
  map_id nullable, created_at
)
```

규칙: 행위자 본인에게는 알림을 만들지 않는다. `notification_prefs`에서 끈 종류는 만들 때 거른다(이미 쌓인 알림은 지우지 않는다). 90일이 지난 알림은 정리 작업(#168)이 지운다. 계정 탈퇴(#155)는 `notifications.api.delete_by_user`가 그 사용자의 알림·설정을 지우고, 지도 정리(#431)는 map_id가 같은 알림을 지우지 않는다(남은 구성원의 알림함에 `map_deleted`가 보여야 한다).

---

## 게스트 전환과 합치기 (v2, #560, 2026-10-20 / 2026-10-24 개정 #694)

게스트가 카카오로 로그인하면(`GET /auth/kakao/login`을 게스트 세션으로 시작 → 콜백) 게스트의 기록을 카카오 계정으로 잇는다. 새 엔드포인트는 없다. 로그인 시작이 게스트 id를 서명한 state 쿠키에 담고, 콜백이 카카오 수단을 찾은 뒤 한 트랜잭션에서 아래 둘 중 하나를 한다. 게스트 행은 먼저 `FOR UPDATE`로 잠근다(같은 게스트로 겹친 콜백은 한쪽만 한다).

| 그 카카오 계정 | 처리 | 다른 모듈 |
| --- | --- | --- |
| 처음(수단이 없다) | 게스트 행에 카카오 수단을 붙인다. 사용자 id 그대로, 표시 이름은 게스트 때 이름 그대로, `guest_invite_token`은 비운다 | 아무것도 하지 않는다 |
| 이미 쓰던 사용자가 있다 | 아래 합치기. 게스트의 기록을 그 사용자로 옮기고 게스트 행을 지운다 | 모듈마다 `reassign_user` |

같은 카카오 계정이 두 게스트에 동시에 붙으면 `unique(provider, provider_user_id)`가 막고, 나중 요청은 합치기로 간다. 어느 쪽이든 실패하면 카카오 로그인은 그대로 성공시키고 게스트 기록은 남긴다(`guest_merged=false`). 2026-10-20 판은 처음 전환도 새 사용자를 만들어 합쳤다. 가장 흔한 전환이 모듈 7개를 거치는 길을 타서 바꿨다(멘토 리뷰 #680).

### 합치기 (이미 쓰던 카카오 계정이 있을 때)

각 모듈은 자기 테이블만 옮긴다 — auth가 다른 모듈의 테이블을 직접 바꾸지 않고 각 `api.py`의 `reassign_user(db, *, from_user_id, to_user_id) -> dict[str, int]`(옮긴 행 수, 커밋은 호출자)를 부른다. 지도별로 충돌하면 **카카오 계정의 기존 값이 이긴다.**

| 모듈 | 옮기는 것 | 충돌 규칙 |
|---|---|---|
| maps | `memberships.user_id`, `invites.created_by` | 같은 지도에 카카오 계정이 이미 구성원이면 게스트의 멤버십은 지운다(역할은 카카오 쪽 그대로). 지도 수 상한(20)은 합칠 때 검사하지 않는다 |
| pins | `pins.created_by`, `reactions.user_id` | 같은 핀에 카카오 계정의 반응이 이미 있으면 게스트의 반응을 지운다 |
| recommend | `recommend_runs.requested_by`, `evidence_lines`의 작성자, `exclusions.requested_by`, 후보의 요청자 | 제안·거절 이력이 (지도, 장소)로 겹치면 게스트 것을 지운다. `attempt_no`는 건드리지 않는다(추천 횟수는 합치지 않는다) |
| shortlist | `shortlist_items.added_by` | 없음 |
| notifications | `notifications.user_id` | `notification_prefs`는 카카오 계정 것을 쓰고 게스트 것은 지운다 |
| feedback | `feedback.user_id` | 없음 |
| agent | `agent_suggestion_views.user_id`, `agent_course_runs.requested_by`, `agent_settings.updated_by`, `agent_suggestions.resolved_by` | 같은 제안을 둘 다 열람했으면 게스트 것을 지운다. 같은 지도에 둘 다 진행 중인 코스 요청이 있으면 게스트 것을 지운다(진행 중은 지도당 한 사람에 하나). 코스 하루 상한은 합치지 않는다(추천 횟수와 같다) |
| auth | 마지막에 게스트 행을 `deleted_at`으로 지운다(탈퇴처럼 반응·근거를 지우지는 않는다 — 이미 옮겼다) | — |

합치기로 사용자가 보는 이름이 게스트 이름에서 카카오 계정의 이름으로 바뀐다(구성원 목록과 핀 작성자 표시는 다시 불러오면 된다).

사용자 기록을 다루는 목록은 탈퇴(`withdraw_user`)와 합치기(`MERGE_STEPS`) 둘이다. 한쪽에만 모듈이 더해지지 않게 "탈퇴 목록에 있는 모듈은 합치기 목록에도 있다"를 테스트로 고정한다(#694). 지도 정리(`maps.purge.PURGE_STEPS`)는 지도 단위라 대상이 다르다. 게스트가 아닌 사용자가 시작하면 아무것도 하지 않는다. 이미 합쳐진(삭제된) 게스트 id로는 다시 합치지 않는다.

---

## common (모든 모듈이 쓰고 realtime만 읽는다)

```
event_log(
  seq bigserial primary key,            -- 단조증가하지만 *커밋 순서와 일치하지 않을 수 있다*
                                         -- (docs/events.md 「전달 보장」 4)
  map_id, channel('public'|'private'),
  recipient_user_id null,               -- channel='private'일 때만
  type, payload jsonb, created_at timestamptz default now()
)
  index(map_id, seq)                    -- 채널별 재전송 조회
  index(created_at)                     -- 보존기간 삭제용
  check ((channel='private') = (recipient_user_id is not null))
```

쓰기: 모든 모듈이 `common.events.record_event(db, event)`로만. 상태 변경과 같은 트랜잭션에
넣는다(`docs/events.md` 「전달 보장」 1). 읽기: `realtime`만.

---

## realtime (5절)

이벤트 발행 계약은 위 `## common`의 `event_log` 참고 — `realtime`은 폴링해서 읽기만 한다.

---

## 열린 항목 (결정 이슈로 별도 확정 — 이 문서는 자리만 잡음)

- 중복 핀 "같은 곳" 판정 기준 (source_id 동일 / 좌표 반경 N m / 이름 유사도) — #33, 보류
- ~~N(구성원 수)의 정의~~ — 2026-10-07 해소(#360): 추천 열림은 ♥/🚫 의견이 달린 핀 1개 이상이라 임계값 N이 없고, 핀 참여율의 분모는 지도 전체 구성원 수다
- 재시도 상한의 집계 단위(#31), 제안·거절 이력의 단위(#42) — 아래 "팀이 결정한 것" 참고(2026-09-22 확정)

## 9/4 회의로 해결된 것 (docs 반영 완료)

- 지도 생성 입력 필드 — #22, 여행 제목 + 시작일·종료일로 확정, 위 `maps` 테이블에 반영
- 구성원 색 — #26, 불필요로 확정, `memberships.color` 제거
- `visit_order` 수동 정렬 — #30, 허용 확정(동선과 무관). `PUT /maps/{mapId}/shortlist/order` 참고
- AI 추천 결과 상태 관리 위치 — #43, 서버 DB 영속 확정. `recommend_runs`/`candidates`는 이제 확정 설계

## 루트가 확정한 것 (2026-09-22)

- **`pins.source_run_id`/`checks` 스키마** — #57. 둘 다 추가하는 쪽으로 확정: `source_run_id`는
  게시 시점 1회성 불투명 참조(추적·표시용, FK 없음, pins가 다시 읽지 않음), `checks`는 게시
  시점에 candidate에서 복사(가드레일 5). 위 `pins` 테이블에 반영. 이유: `source_run_id`는 이미
  목 서버(`contracts/mocks`)가 쓰고 있어 없애면 FE 쪽 재작업이 필요하고,
  `candidates.lat/lng` 비정규화와 같은 논리로 "1회성 복사"는 "실시간 모듈 간 조회 금지" 원칙과
  충돌하지 않는다.
- **`Candidate.permissions` 필드 추가 여부** — #64. 추가하는 쪽으로 확정: 이미 있는 공용
  `Permissions` 스키마에 `can_publish`를 추가하고 `Candidate`가 이를 참조한다(`Pin`/`EvidenceLine`
  등 다른 리소스와 같은 패턴). "FE가 권한 규칙을 재구현하지 않는다"(permissions.md) 원칙과
  일관되고, `authz.core.can()`이 이미 `recommend.publish`를 판정할 수 있어 구현 비용도 낮다.
  `docs/api-spec.yaml`·`docs/CHANGELOG-api.md`에 반영.
- **게시 버튼 공개여부 구분 표시** — #27, FE가 결정하기로 함(투명도로 구분 제안). 백엔드
  블로커 아님 — 이슈 종료.

## 팀이 결정한 것 (2026-09-22, 황준영·itsmedoyun 합의 — 루트는 기록만)

- **재시도 상한의 집계 단위** — #31. 개인(requested_by) 단위, 카테고리 구분 없음, 상한
  5회(기존 3회 잠정치에서 상향). 위 `recommend_runs.attempt_no`에 반영.
- **제안·거절 이력의 단위** — #42. 개인 단위 — 한 사람이 거절한 곳도 다른 사람의 추천에는
  그대로 뜬다. 위 `exclusions` 테이블에 `unique(map_id, requested_by, place_id)`로 반영.

이 둘이 정해지면서 recommend 코어 스키마를 막던 미결 항목(#31·#42·#57·#64)이 전부 해소됐다 —
다음은 #6(AI 추천 탭) 하위 이슈 분할과 recommend 코어 구현.
