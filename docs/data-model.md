# 데이터 모델

작성 기준: `최종기획안.md`(2·5·9절) + `docs/architecture.md`
DB: PostgreSQL 17 + PostGIS(직선거리, 13절 참고). 실시간 보조: Redis(세션/멱등키, SSE 재전송 버퍼).

이 문서는 테이블 단위 스키마다. 각 모듈은 자신이 소유한 테이블만 쓰기 접근하고, 다른 모듈 테이블은 해당 모듈의 함수/API를 통해서만 읽는다(`architecture.md` 1절).

---

## auth / maps

```
users(
  id, provider('kakao'), provider_user_id, display_name,
  created_at, deleted_at            -- 탈퇴 시 soft delete, 12절
)

maps(
  id, title, start_date, end_date, member_count_expected,
  created_by, created_at
)
  CHECK (end_date >= start_date)   -- 9/4 결정 #22: 여행 제목 + 시작일·종료일. day_count·region_hint는 폐기

memberships(
  id, map_id, user_id, role('member'|'owner'),   -- authz 참고. color는 9/4 결정 #26으로 폐기(구성원 구분에 색 불필요)
  joined_at
)
  unique(map_id, user_id)

invites(
  token, map_id, created_by, expires_at, used_count
)
```

---

## pins (5-1, 5-2, 4절)

```
pins(
  id, map_id, category('음식점'|'카페'|'숙소'|'관광지'),
  kind('일반'|'AI추천'|'확정'),        -- 확정이 나머지 둘을 덮어쓴다(5-2)
  origin('direct'|'ai'),               -- kind와 별개. 원래 태생은 안 바뀐다(4절: 반대 많아도 모양 불변)
  place_id references places(id),
  geom geography(Point,4326),
  visibility('public'|'private'),      -- 5-5-1: AI 후보는 private로 시작
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

reactions(
  id, pin_id, user_id, type('like'|'neutral'|'against'),  -- ♥/△/🚫. '?'미확인은 행 없음으로 표현
  reason_text, reason_chip_ids jsonb,   -- 반대는 reason 필수(가드레일 3)
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
  id, source('kakao'|'google'|'naver'),
  source_id,                            -- 어댑터가 준 원본 식별자
  name, category, address, phone, place_url,
  geom geography(Point,4326),
  first_seen_at, last_synced_at
)
  unique(source, source_id)

place_facts(
  place_id references places(id),
  fact_key,                             -- 'contains_shellfish' | 'spicy_focused' | 'price_bucket' | ...
                                         -- constraints.md의 라벨링 대상만 저장: 실격 6개 + 선호 조건
                                         -- is_open/within_radius는 코드 판정이라 여기 없다(실시간 조회·좌표 계산)
  value,                                 -- boolean/enum, jsonb로 통일 저장
  confidence('known'|'unknown'),        -- D4: unknown_policy는 constraints.md 참고
  source_layer(1|2|3),                  -- architecture.md 3층 모델
  model_version null,                   -- source_layer=3일 때만
  labeled_at
)
  primary key(place_id, fact_key)
```

**`place_facts`는 캐시가 아니다.** TTL로 만료시키지 않는다 — 원본이 따로 없는 1차 데이터이기 때문이다(멘토: "자체 DB 구축이 곧 해자"). 가게 정보가 실제로 바뀌었다고 판단되면 `labeled_at` 기준으로 재라벨링 잡을 새로 돌려 **덮어쓴다**(버전 갱신이지 캐시 무효화가 아니다).

`price_bucket`처럼 압축된 값만 저장하고 원본 가격 숫자는 저장하지 않는다(architecture.md 2절, 차원 압축).

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
  attempt_no,                           -- 재시도 상한. 집계 단위·수치는 #31 미확정(현재 3회는 잠정치)
  created_at
)

evidence_lines(
  id, run_id, author_id,                -- "자기가 쓴 것만 뺄 수 있다"(5-5) — author_id로 권한 판정
  source('reaction'|'manual'),
  text, chip_id null,
  badge('required'|'preferred'|'reference'),  -- 꼭/선호/참고
  fact_key null,                        -- 실격/선호 조건에 매핑되면 채움
  circle_anchor_pin_id null, circle_radius_m null,  -- 반경 사유(5-6-1)
  is_active boolean default true,       -- '-'로 뺀 상태
  created_at
)

regions(
  id, run_id, signature,                -- 5-6-1 겹침 판정 서명. 무효화 규칙: signature 재계산 시 값이 바뀌면 재확인
  geom geography, confirmed boolean, confirmed_at
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
  -- "다시 추천 받기" 시 현재 뜬 후보 전체가 여기 들어간다(3절, 루프가 닫힌다)
  -- map_id 단위로 쌓는 것으로 우선 설계했으나, #42("제안·거절 이력의 단위") 미확정 —
  -- 개인 단위(requested_by 포함)로 정해지면 unique 제약·조회 조건이 바뀐다
```

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
- N(구성원 수)의 정의 — #32, "온라인 구성원 현재 수"로 답은 나왔으나 ceil(N/2) 임계값 자체를 없앨지는 코멘트 상 아직 불명확
- 재시도 3회 상한의 집계 단위(#31), 제안·거절 이력의 단위(#42) — 아래 "아직 팀이 정해야 하는 것" 참고(BE 내부 이견 그대로 남음)

## 9/4 회의로 해결된 것 (docs 반영 완료)

- 지도 생성 입력 필드 — #22, 여행 제목 + 시작일·종료일로 확정, 위 `maps` 테이블에 반영
- 구성원 색 — #26, 불필요로 확정, `memberships.color` 제거
- `visit_order` 수동 정렬 — #30, 허용 확정(동선과 무관). `PUT /maps/{mapId}/shortlist/order` 참고
- AI 추천 결과 상태 관리 위치 — #43, 서버 DB 영속 확정. `recommend_runs`/`candidates`는 이제 확정 설계

## 루트가 확정한 것 (2026-09-22)

- **`pins.source_run_id`/`checks` 스키마** — #57. 둘 다 추가하는 쪽으로 확정: `source_run_id`는
  게시 시점 1회성 불투명 참조(추적·표시용, FK 없음, pins가 다시 읽지 않음), `checks`는 게시
  시점에 candidate에서 복사(가드레일 5). 위 `pins` 테이블에 반영. 이유: `source_run_id`는 이미
  목 서버(`contracts/mocks`)가 private 판정에 쓰고 있어 없애면 FE 쪽 재작업이 필요하고,
  `candidates.lat/lng` 비정규화와 같은 논리로 "1회성 복사"는 "실시간 모듈 간 조회 금지" 원칙과
  충돌하지 않는다.
- **`Candidate.permissions` 필드 추가 여부** — #64. 추가하는 쪽으로 확정: 이미 있는 공용
  `Permissions` 스키마에 `can_publish`를 추가하고 `Candidate`가 이를 참조한다(`Pin`/`EvidenceLine`
  등 다른 리소스와 같은 패턴). "FE가 권한 규칙을 재구현하지 않는다"(permissions.md) 원칙과
  일관되고, `authz.core.can()`이 이미 `recommend.publish`를 판정할 수 있어 구현 비용도 낮다.
  `docs/api-spec.yaml`·`docs/CHANGELOG-api.md`에 반영.
- **게시 버튼 공개여부 구분 표시** — #27, FE가 결정하기로 함(투명도로 구분 제안). 백엔드
  블로커 아님 — 이슈 종료.

## 아직 팀이 정해야 하는 것 (실제 이견 있음 — 루트가 임의로 결정하지 않음)

- **재시도 3회 상한의 집계 단위** — #31. 황준영은 "지도+카테고리당, 상한 상향"을, 김도윤은
  "개인 단위"를 제안하고 그대로 남아 있다. `recommend_runs.attempt_no` 계산 로직이 이 결정을
  기다린다.
- **제안·거절 이력의 단위** — #42. 황준영은 "지도 단위"를, 김도윤은 "개인 단위"를 제안하고
  그대로 남아 있다(위와 같은 두 사람, 같은 성격의 이견). `exclusions` 테이블의 unique 제약이
  이 결정에 따라 달라진다.
