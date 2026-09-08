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
  created_by, created_at, deleted_at
)
  unique(map_id, place_id) where deleted_at is null   -- 중복 핀 판정(가드레일 6). 판정 기준은 #33(보류)에서 별도 확정

reactions(
  id, pin_id, user_id, type('like'|'neutral'|'against'),  -- ♥/△/🚫. '?'미확인은 행 없음으로 표현
  reason_text, reason_chip_ids jsonb,   -- 반대는 reason 필수(가드레일 3)
  created_at, updated_at
)
  unique(pin_id, user_id)

shortlist_items(
  id, map_id, pin_id, added_by, added_at,
  visit_order int null                 -- 5-10 자동계산 결과 + #30 수동 정렬(허용 확정) 둘 다 이 컬럼을 쓴다
)
  unique(map_id, pin_id)
```

`kind`가 바뀌는 유일한 경로는 확정 리스트 추가/제외(5-3)다. `origin`은 불변이며 "이미 제안·거절된 곳" 판정(가드레일 6)과 무관하다 — 그건 `recommend.exclusions`가 따로 갖는다.

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
  -- map_id 단위로 쌓는 것으로 우선 설계했으나, #42("제안·거절 이력의 단위") 미확정 —
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

- 중복 핀 "같은 곳" 판정 기준 (source_id 동일 / 좌표 반경 N m / 이름 유사도) — #33, 보류
- 재시도 3회 상한의 집계 단위·상한 수치 — #31, BE 논의 중 (황준영: 지도+카테고리당·상한 상향 / 김도윤: 개인 단위)
- N(구성원 수)의 정의 — #32, "온라인 구성원 현재 수"로 답은 나왔으나 ceil(N/2) 임계값 자체를 없앨지는 코멘트 상 아직 불명확
- **제안·거절 이력의 단위** — #42, 지도 vs 개인 단위로 황준영·김도윤 의견이 갈려 아직 미확정. `exclusions` 스키마는 지도 단위(현재 설계)를 전제로 함

## 9/4 회의로 해결된 것 (docs 반영 완료)

- 지도 생성 입력 필드 — #22, 여행 제목 + 시작일·종료일로 확정, 위 `maps` 테이블에 반영
- 구성원 색 — #26, 불필요로 확정, `memberships.color` 제거
- `visit_order` 수동 정렬 — #30, 허용 확정(동선과 무관). `PUT /maps/{mapId}/shortlist/order` 참고
- AI 추천 결과 상태 관리 위치 — #43, 서버 DB 영속 확정. `recommend_runs`/`candidates`는 이제 확정 설계
