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
  id, title, region_hint, day_count, member_count_expected,
  created_by, created_at
)

memberships(
  id, map_id, user_id, color, role('member'|'owner'),   -- authz 참고
  joined_at
)
  unique(map_id, user_id)

invites(
  token, map_id, created_by, expires_at, used_count
)
```

`region_hint`·`day_count` 등 지도 생성 입력값은 결정 이슈(#15 분리분 "지도 생성 입력값 정의") 확정 후 필드를 확정한다 — 현재는 자리만 잡아둔다.

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
  created_by, created_at, deleted_at
)
  unique(map_id, place_id) where deleted_at is null   -- 중복 핀 판정(가드레일 6). 판정 기준은 결정 이슈로 별도 확정

reactions(
  id, pin_id, user_id, type('like'|'neutral'|'against'),  -- ♥/△/🚫. '?'미확인은 행 없음으로 표현
  reason_text, reason_chip_ids jsonb,   -- 반대는 reason 필수(가드레일 3)
  created_at, updated_at
)
  unique(pin_id, user_id)

shortlist_items(
  id, map_id, pin_id, added_by, added_at,
  visit_order int null                 -- 5-10 자동계산 결과. 수동 정렬 허용 여부는 결정 이슈 미결
)
  unique(map_id, pin_id)
```

`kind`가 바뀌는 유일한 경로는 확정 리스트 추가/제외(5-3)다. `origin`은 불변이며 "이미 제안·거절된 곳" 판정(가드레일 6)과 무관하다 — 그건 `recommend.exclusions`가 따로 갖는다.

---

## places / place_facts (architecture.md 2절 — 자체 장소 DB)

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
                                         -- 8개 실격조건(5-7) + 선호 조건 전부가 fact_key로 존재
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

> `recommend_runs`·`candidates`는 **서버 DB 영속 저장**을 전제로 설계했다. 결정 이슈("AI 추천 결과 상태 관리 위치")가 휘발성(세션/캐시) 쪽으로 정해지면 이 두 테이블은 Redis TTL 키나 클라이언트 상태로 옮겨가야 한다 — 지금은 한쪽 안이다.

```
recommend_runs(
  id, map_id, category, requested_by, status,
  attempt_no,                           -- 3회 상한. 스코프는 결정 이슈 미결
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
  rank, checks jsonb,                   -- 조건별 충족 체크(가드레일 5)
  member_fulfillment jsonb,
  published_pin_id null,                -- 5-5-1 게시 후 연결
  created_at
)

exclusions(
  map_id, category, place_id, reason('proposed'|'dismissed'),
  run_id, requested_by, created_at
)
  -- "다시 추천 받기" 시 현재 뜬 후보 전체가 여기 들어간다(3절, 루프가 닫힌다)
  -- map_id 단위로 쌓는 것으로 우선 설계했으나, 결정 이슈("제안·거절 이력의 단위") 미결 —
  -- 개인 단위(requested_by 포함)로 정해지면 unique 제약·조회 조건이 바뀐다
```

---

## realtime (5절)

```
event_log(
  seq bigserial primary key,            -- 단조증가, 재동기화 기준(events.md)
  map_id, channel('public'|'private'),
  recipient_user_id null,               -- channel='private'일 때만
  type, payload jsonb, created_at
)
```

---

## 열린 항목 (결정 이슈로 별도 확정 — 이 문서는 자리만 잡음)

- 중복 핀 "같은 곳" 판정 기준 (source_id 동일 / 좌표 반경 N m / 이름 유사도)
- `visit_order` 수동 정렬 허용 여부와 자동 재계산 시 유지 규칙
- 재시도 3회 상한의 집계 단위 (map+category / map+user 등)
- N(구성원 수)의 정의 — 전체 vs 온라인, 변동 시 진행 중 run 처리
- 지도 생성 입력 필드 확정 (`maps` 테이블 컬럼 확정)
- **제안·거절 이력의 단위** — `exclusions`를 지도 단위로 쌓을지 개인 단위로 쌓을지 (README "정해야 할 것" #5)
- **AI 추천 결과의 상태 관리 위치** — `recommend_runs`/`candidates`를 서버 DB에 영속 저장할지, 휘발성(세션/캐시)으로 둘지 (README "정해야 할 것" #8)
