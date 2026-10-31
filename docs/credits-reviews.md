# 크레딧과 장소 후기 — 구현 명세

> 추천 탭 광고의 `docs/ads.md`와 같은 기능 명세다. 정본은 여전히 `docs/api-spec.yaml`·`docs/data-model.md`·`docs/errors.md`이고, 이 문서와 다르면 그쪽을 따른다.
> 상태: 결정 반영 (2026-11-01, #432). 작업은 #948~#954.

## 0. 한 줄 요약

기능별 사용 상한(코스 하루 5회, 추천 지도·사람당 10회)을 없앤다. 정식 계정은 크레딧 30으로 시작하고, 사람이 누른 AI 실행(추천, 코스)마다 1씩 빠진다. 실행이 결과 없이 끝나면 돌려준다. 재충전은 장소 후기를 처음 쓸 때 +10 하나뿐이다. 광고 충전은 하지 않는다. 게스트는 AI 추천과 코스를 쓰지 않는다.

## 1. 배경

- 페이즈 1 목표: 크레딧이 여행 1건 계획에 불편을 주지 않는다. 페이즈 2에서 유료 크레딧으로 수익화한다.
- 모델 원가(실측, #870): 실행 1번 평균 추천 ₩0.86, 코스 ₩0.92, 「+」 근거 추가 ₩0.12. 6명이 의견이 갈린 여행도 사람당 약 ₩2. 1크레딧 ≈ 원가 ₩1.
- 그래서 크레딧은 원가 회수 장치가 아니라 가치 표시와 후기 유도 장치다. 후기 보상에는 상한을 두지 않는다(비용 통제 장치가 아님을 감수).
- 상한이 지도마다였던 탓에 지도를 지우고 다시 만들면 횟수가 다시 생겼다(#432, 멘토 리뷰 #380). 사람마다 세는 크레딧이 그 구멍을 닫는다.

## 2. 용어

| 말 | 뜻 |
|---|---|
| 크레딧 | 사람(users 행)마다 하나인 잔액. 지도와 무관하다 |
| 정식 계정 | 로그인 수단이 있는 사용자. 게스트(#472, #694)가 아닌 사람 |
| 원장 | 잔액이 바뀐 모든 이유의 기록(`credit_ledger`). **원본은 원장이다** |
| 후기 | 자체 DB 장소(`places.id`)에 붙는 별점 + 글. 지도·핀이 아니라 장소에 붙는다 |

## 3. 크레딧 규칙

### 3.1 지급

- 정식 계정에 30(`INITIAL_CREDITS`). 계정 행은 **처음 쓰기(차감 또는 후기 보상) 때** 만들고, 그때 원장에 `initial` +30을 같이 남긴다.
- 계정 행이 없을 때 읽기(`GET /credits/me`, 잔액 확인)는 30으로 본다. GET은 쓰지 않는다.
- 게스트에는 계정을 만들지 않는다. **게스트는 AI 추천과 코스를 쓰지 않는다**(#432 결정 A). 게스트 판정은 `credits`가 `auth.api.guest_user_ids`로 한 곳에서 한다(호출하는 모듈이 `is_guest`를 넘기지 않는다).

### 3.2 가격 (정하는 곳: `credits/constants.py` 한 곳)

| feature (= `llm_calls.feature` 라벨) | 차감 | 실행 1번당 모델 호출 | 비고 |
|---|---|---|---|
| `recommend_run` | 1 | 0~n (글 사유 10줄당 1) | 모델을 안 부르는 실행도 1. 누르기 전에 값이 정해진다 |
| `course` | 1 | 2~6 (평균 3) | |
| `evidence_add` | 0 (가격표에 없음) | 1 이상 | 「+」 근거 추가. run당 글 10개(`recommend/core.py`의 `MANUAL_EVIDENCE_LIMIT`, 넘으면 409 `EVIDENCE_LIMIT`)가 남용을 막는다 |
| `agent_diagnose`, `agent_summary` | 0 (가격표에 없음) | — | 서버 백그라운드. 지도 하루 상한(구성원 수 × 4) 유지 |

다른 모듈은 가격 숫자를 들지 않는다. `credits.api.charge(feature=...)`만 부른다. 화면은 가격과 보상을 `GET /credits/me`로 받고 숫자를 적지 않는다.

### 3.3 차감과 환불

- **차감은 실행을 저장하는 트랜잭션 안에서** 한다. 저장이 실패하면 차감도 같이 롤백된다 → 그 경우 환불이 필요 없다.
- **모델 호출 전에 잔액을 읽기만으로 확인**한다(`check_can_spend`). 모자라면 모델을 부르기 전에 402.
- **환불**: 실행 행은 커밋됐는데 결과 없이 끝난 경우만. 코스의 `ENGINE_ERROR`, `INTERRUPTED`.
- **추천에는 환불 경로가 없다**(#432 D6). v1 추천은 `failed`를 쓰지 않고 실패하면 롤백한다(`recommend/core.py` 설명, `docs/events.md` 「v1에서 발행하지 않는 이벤트」). 차감이 같은 트랜잭션이라 같이 롤백된다. 나중에 커밋 뒤 `failed`로 끝나는 경로가 생기면 그때 `refund(feature="recommend_run")`를 단다.
- 결과 0곳(`NO_RESULTS`)은 결과다(가드레일 2). 환불하지 않는다.
- 멱등: 원장 `ref_id` UNIQUE. 같은 실행 이중 차감, 이중 환불, 같은 장소 후기 보상 두 번이 구조적으로 막힌다.

| `ref_id` | reason | delta |
|---|---|---|
| `initial:<user_id>` | `initial` | +30 |
| `recommend_run:<run_id>`, `course:<run_id>` | `spend` | -가격 |
| `refund:<차감 ref_id>` | `refund` | +가격 |
| `review:<user_id>:<place_id>` | `review` | +10 |

페이즈 2의 구매는 reason `purchase`로 같은 원장에 더한다(지금은 만들지 않는다).

광고 충전은 이 작업(크레딧 전환, 후기)이 끝난 뒤 따로 한다. 그때도 같은 원장에 reason `ad`, `ref_id = ad:<광고 세션 id>`로 더하고, 보상은 `credits.api`에 함수 하나(`grant_ad`)를 여는 것으로 끝나게 둔다. 지금 단계에서 미리 만들지 않는다.

### 3.4 잔액과 동시성

- `credit_accounts.balance`는 **원장 합을 담아 두는 값**이다(원본이 아니다). 행 잠금과 `CHECK (balance >= 0)`을 걸 자리가 필요해서 둔다. 잔액을 바꾸는 함수는 원장 행과 `balance`를 같은 트랜잭션에서 함께 바꾼다. 둘이 같은지는 테스트가 본다(12절).
- 잔액이 바뀌는 모든 경로는 그 사람의 `credit_accounts` 행을 `SELECT ... FOR UPDATE`로 잡고 시작한다. 같은 사람의 차감·환불·보상이 줄을 선다. 계정 생성은 `INSERT ... ON CONFLICT (user_id) DO NOTHING RETURNING`으로 초기 지급이 한 번만 된다.

### 3.5 잔액 부족과 게스트

- 잔액 부족: `402 CREDIT_INSUFFICIENT`, `detail = { required, balance }`.
  - 화면: "크레딧이 부족해요. 후기를 쓰면 {review_reward} 크레딧을 드려요" + 「후기 쓰러 가기」(확정 탭으로). `review_reward`는 `GET /credits/me`에서 받는다.
- 게스트(추천, 코스, `GET /credits/me`): `403 GUEST_NOT_ALLOWED`, `detail = { initial_credits }`.
  - 화면: "카카오로 로그인하면 {initial_credits} 크레딧을 드려요" + 카카오 전환. 게스트는 `GET /credits/me`를 받을 수 없으므로 숫자는 이 `detail`에서만 온다(정책 값을 화면에 적지 않는다, #733).

## 4. 없애는 상한과 남기는 보호

| 장치 | 지금 | 결정 |
|---|---|---|
| `COURSE_LIMIT` / `COURSE_DAILY_LIMIT` | 코스 사람당 하루 5회 | 삭제(#950). 계약은 폐지 예정으로 두고 #954에서 지운다 |
| `RETRY_LIMIT` / `ATTEMPT_LIMIT` | 추천 지도·사람당 10회 (새 추천, 다시 찾기, 근거 고치기 모두 검사) | 삭제(#949). 계약은 폐지 예정으로 두고 #954에서 지운다 |
| `attempt_no` 열과 `lock_requester_attempts` | 시도 번호, 같은 번호 중복 방지(#811) | **유지** (번호는 계속 매긴다) |
| 응답의 `attempt_limit` | FE가 "N/10회" 표시 | 폐지 예정(`deprecated`). FE가 안 쓰게 된 뒤(#952) #954에서 지운다 |
| `COURSE_IN_PROGRESS`, `REQUEST_IN_PROGRESS`, `Idempotency-Key` | 진행 중 중복 막기 | 유지 |
| `MANUAL_EVIDENCE_LIMIT` (`EVIDENCE_LIMIT`) | 직접 추가 글 run당 10개 | 유지 |
| 지도 하루 모델 상한 | 구성원 수 × 4 (백그라운드) | 유지 |

계약을 한 번에 지우지 않는 이유: FE는 생성된 타입으로 `attempt_limit`을 읽고 있어서, 스펙에서 먼저 지우면 develop의 FE 빌드가 깨진다. 서버도 구현 PR 전까지 `RETRY_LIMIT`을 낸다. 그래서 새 것을 먼저 더하고(이 문서의 계약 PR), 각 구현이 옛 것을 쓰지 않게 된 뒤 지운다(#954).

상한이 사라진 뒤 무료로 남는 경로(#432 D5):
- 「다시 찾기」(`POST /runs/{runId}/retry`): 자체 DB 검색뿐, 모델 호출 없음.
- 「근거 고치기」(`PATCH /runs/{runId}/evidence`): ×(끄기·켜기)는 모델 없음. ＋(새 글)만 그 글을 ②로 구조화(`evidence_add`, 0 크레딧, run당 글 10개).
- 최악의 경우 실행 1번(₩0.86) + ＋ 10번(₩1.2)에 1크레딧이다. 금액이 작아 감수하고 `llm_calls`로 지켜본다(10절).

## 5. 장소 후기 규칙

| 항목 | 규칙 |
|---|---|
| 대상 | 자체 DB 장소를 가리키는 핀(`source = db`, `place_id` 있음). 실시간 핀(`source = live`)은 `422 PLACE_NOT_SUPPORTED` |
| 붙는 곳 | `places.id`. 같은 장소의 후기는 어느 지도의 핀에서 봐도 같다 |
| 쓰는 사람 | 정식 계정. 게스트는 `403 GUEST_NOT_ALLOWED`. 방문 확인 없음 |
| 보는 사람 | 그 핀을 볼 수 있는 사람(그 지도 구성원). 다른 지도 사람이 쓴 후기도 보인다 |
| 작성자 표시 | **이름을 보이지 않는다**(#432 결정 B). 서버는 작성자 이름을 내리지 않고 `is_mine`만 내린다. 화면은 내 후기를 「나」, 나머지를 「핑고 사용자」로 쓴다. 모르는 사람의 표시 이름이 다른 지도에 나가지 않게 한다(기획안 12절) |
| 별점 | 필수, 정수 1~5 |
| 글 | 필수, 앞뒤 공백을 걷은 뒤 1자 이상 500자 이하(`REVIEW_BODY_MAX = 500`). 어기면 `422 VALIDATION_ERROR` |
| 개수 | 한 사람이 한 장소에 하나. 수정·삭제 가능 |
| 보상 | 그 장소에 처음 쓸 때 +10. 상한 없음. 별점과 무관. 수정은 보상 없음. 지웠다 다시 써도 `ref_id`가 같아 보상 없음 |
| 공개 | 평균 별점(소수 첫째 자리), 후기 수, 최신순 목록 |
| 신고 | 후기마다 한 사람 한 번(멱등). 자기 후기는 신고 불가(422 `VALIDATION_ERROR`) |
| 숨김 | 관리 스크립트로만(#432 D8). `reviews/scripts/reports.py`로 신고가 많은 순으로 보고, `reviews/scripts/hide.py`로 숨기거나 되돌린다. 숨긴 후기는 목록·평균·개수에서 빠진다. 작성자 본인에게도 안 보인다. 신고 수로 자동 숨기는 기준은 실제 데이터를 본 뒤 정한다 |
| 모델 | 후기 글은 추천, ②, 에이전트에 보내지 않는다. `place_facts`를 바꾸지 않는다 |
| 로그 | 후기 글을 로그에 남기지 않는다(`backend/CLAUDE.md` 실패 로그 규칙) |
| 사전 고지 | 작성 시트에 "후기를 쓰면 크레딧을 드려요. 별점과 상관없이 같아요." |

**후기는 SNS가 아니다**(#432 결정 C, 기획안 11절). 후기는 장소에 붙는 정보이고, 팔로우·댓글·좋아요·프로필·피드가 없으며 작성자 이름을 보이지 않는다. 후기에 댓글이나 작성자 프로필을 붙이자는 요청은 범위 밖(SNS)이다. 다만 모르는 사람이 쓴 글을 보여 주는 것이라 신고와 숨김 운영이 필요하다(10절).

## 6. 데이터 모델

정본은 `docs/data-model.md` 「크레딧」「장소 후기」 절이다. 모든 사용자 id 열과 `place_id`는 FK 없음(모듈 경계, #760, `ads.place_id` 선례). 마이그레이션 번호는 정해 두지 않는다. 각 PR이 develop의 다음 번호를 쓰고, 먼저 머지되는 쪽이 가져가며 뒤 PR이 develop을 받아 맞춘다(열린 #922도 번호를 바꿔야 한다).

```
credit_accounts
  user_id     varchar  PK
  balance     integer  NOT NULL   CHECK (balance >= 0)   -- 원장 합(3.4)
  updated_at  timestamptz NOT NULL default now()

credit_ledger
  id          uuid PK
  user_id     varchar  NOT NULL
  delta       integer  NOT NULL
  reason      varchar  NOT NULL   -- initial | spend | refund | review
  ref_id      varchar  NOT NULL UNIQUE
  created_at  timestamptz NOT NULL default now()
  INDEX (user_id, reason, created_at)

reviews
  id          uuid PK
  place_id    varchar  NOT NULL
  user_id     varchar  NOT NULL
  rating      smallint NOT NULL   CHECK (rating BETWEEN 1 AND 5)
  body        text     NOT NULL   CHECK (char_length(body) BETWEEN 1 AND 500)
  created_at  timestamptz NOT NULL default now()
  updated_at  timestamptz NOT NULL default now()
  hidden_at   timestamptz NULL
  UNIQUE (place_id, user_id)
  INDEX (place_id, created_at DESC, id DESC) WHERE hidden_at IS NULL

review_reports
  review_id   uuid     NOT NULL REFERENCES reviews(id) ON DELETE CASCADE
  reporter_id varchar  NOT NULL
  created_at  timestamptz NOT NULL default now()
  PRIMARY KEY (review_id, reporter_id)
```

### 계정 수명 (`auth/service.py`)

| 모듈 | `WITHDRAW_STEPS` | `MERGE_STEPS` (`reassign_user`) |
|---|---|---|
| credits | `delete_by_user`: 계정·원장 삭제 | 게스트는 계정이 없다. 혹시 있으면 옮기지 않고 지운다(초기 지급 두 번 방지) |
| reviews | 후기는 남긴다(작성자 이름은 원래 보이지 않는다). 그 사람이 한 신고는 지운다 | 게스트는 후기·신고를 못 쓴다. 옮길 것 없음(멱등 no-op) |

`integration/test_user_data_lists.py`에 새 사용자 id 열 4개(`credit_accounts.user_id`, `credit_ledger.user_id`, `reviews.user_id`, `review_reports.reporter_id`)를 등록한다.

## 7. API

모두 로그인 필요. 응답 필드는 `docs/api-spec.yaml`이 정본이다(`credits`, `reviews` 태그).

### credits

`GET /credits/me` → 200 `CreditBalance`

```json
{ "balance": 27, "prices": { "recommend_run": 1, "course": 1 }, "review_reward": 10 }
```

게스트는 403 `GUEST_NOT_ALLOWED`(`detail.initial_credits`). 계정 행이 없으면 `balance = 30`(쓰지 않음).

### reviews (핀 기준 — #432 D1)

FE는 자체 `places.id`를 모른다(`Pin` 응답에 없다). 그래서 핀으로 부르고 서버가 `pins.api.get_pin_for_viewer(...).place_id`로 장소를 찾는다. 권한은 그 핀의 지도 구성원(핀 조회와 같은 액션, 새 권한 액션 없음).

| 메서드와 경로 | 본문 | 성공 | 실패 |
|---|---|---|---|
| `GET /pins/{pinId}/reviews?cursor=` | — | 200 `ReviewPage` | 404, 422 `PLACE_NOT_SUPPORTED`(live 핀) |
| `PUT /pins/{pinId}/reviews/me` | `{ rating, body }` | 200 `ReviewSaved` | 403 `GUEST_NOT_ALLOWED`, 404, 422 |
| `DELETE /pins/{pinId}/reviews/me` | — | 204 | 404(내 후기 없음) |
| `POST /reviews/{reviewId}/reports` | — | 204 (이미 신고했어도 204) | 403 `GUEST_NOT_ALLOWED`, 404(없거나 숨김, 볼 수 없는 후기), 422(내 후기) |

```json
// ReviewPage
{
  "summary": { "average_rating": 4.3, "count": 12 },
  "limits": { "body_max": 500 },
  "mine": { "id": "…", "rating": 5, "body": "…", "created_at": "…", "updated_at": "…" },
  "items": [
    { "id": "…", "rating": 4, "body": "…", "created_at": "…", "updated_at": "…", "is_mine": false }
  ],
  "next_cursor": "…"
}
// ReviewSaved
{ "review": { "id": "…", "rating": 5, "body": "…", "created_at": "…", "updated_at": "…" },
  "credited": 10, "balance": 40 }
```

- `summary.average_rating`: 후기가 없으면 `null`. 숨김 제외.
- `limits.body_max`: FE가 500을 적지 않게 응답으로 내린다(정책 값은 응답으로).
- `mine`: 내 후기(숨김이 아니면). 없으면 필드 생략. `items`에도 `is_mine = true`로 들어 있다.
- 작성자 이름 필드는 없다(결정 B). 화면이 `is_mine`으로 「나」/「핑고 사용자」를 고른다.
- 페이지: 20개, `(created_at, id)` 내림차순 커서.
- `credited`: 처음 쓴 저장이면 10, 수정이면 0. `balance`: 저장 뒤 잔액.
- `POST /reviews/{reviewId}/reports`는 후기 id로 부른다. 신고하는 사람이 그 후기를 볼 수 있어야 한다 — 그 장소를 가리키는 핀이 있는 지도의 구성원이어야 하고, 아니면 404다.

### 기존 엔드포인트 변경

| 엔드포인트 | 변경 |
|---|---|
| `POST /maps/{mapId}/runs` | 402 `CREDIT_INSUFFICIENT`, 403 `GUEST_NOT_ALLOWED` 추가. 429 `RETRY_LIMIT` 폐지 예정 |
| `POST /runs/{runId}/retry`, `PATCH /runs/{runId}/evidence` | 429 `RETRY_LIMIT` 폐지 예정. 차감 없음 |
| `RecommendRun`, `RunSummary` | `attempt_limit` 폐지 예정. `attempt_no`는 유지 |
| `POST /maps/{mapId}/courses` | 402, 403 `GUEST_NOT_ALLOWED` 추가. 429 `COURSE_LIMIT` 폐지 예정 |

### 에러 코드 (`docs/errors.md`)

| 코드 | 상태 | 변경 |
|---|---|---|
| `CREDIT_INSUFFICIENT` | 402 | 신규. `detail { required, balance }` |
| `GUEST_NOT_ALLOWED` | 403 | 범위 확대: 지도 만들기 + 추천·코스·잔액 조회(`detail { initial_credits }`) + 후기 쓰기·신고 |
| `PLACE_NOT_SUPPORTED` | 422 | 범위 확대: live 핀의 후기 |
| `COURSE_LIMIT`, `RETRY_LIMIT` | 429 | 폐지 예정(#954에서 삭제) |

## 8. 모듈과 연결점

새 모듈 2개(#432 D2). 가격과 게스트 크레딧 규칙은 `credits`, 후기 규칙은 `reviews`가 한 곳에서 정한다.

### `credits.api` (다른 모듈이 부르는 유일한 접점)

```python
def check_can_spend(db, *, user_id: str, feature: str) -> None:
    """읽기만. 게스트면 403 GUEST_NOT_ALLOWED(detail.initial_credits), 잔액 < 가격이면 402 CREDIT_INSUFFICIENT. 모델 호출 전에 부른다."""

def charge(db, *, user_id: str, feature: str, run_id: str) -> int:
    """실행 저장과 같은 트랜잭션에서 가격만큼 뺀다. ref_id = f"{feature}:{run_id}". 남은 잔액.
    읽기 확인과 쓰기 사이에 잔액이 줄었으면 여기서 402(모델은 이미 불렸다 — 드문 경합으로 받아들인다)."""

def refund(db, *, feature: str, run_id: str) -> bool:
    """결과 없이 끝난 실행의 차감을 돌려준다. 멱등. 돌려줬으면 True."""

def grant_review(db, *, user_id: str, place_id: str) -> int:
    """그 장소 첫 후기 보상. 받은 크레딧(10 또는 0). 게스트면 0(호출 전에 reviews가 막는다)."""

def delete_by_user(db, *, user_id: str) -> int: ...
def reassign_user(db, *, from_user_id: str, to_user_id: str) -> dict[str, int]: ...
```

### 부르는 곳

| 모듈 | 위치 | 할 일 | 이슈 |
|---|---|---|---|
| `recommend` | `flows._create_run` | 준비 확인 뒤, 모델(②) 전에 `check_can_spend(feature="recommend_run")`. `service.create_run(...)` 직후 같은 트랜잭션에서 `charge(..., run_id=str(run.id))` | #949 |
| `recommend` | `check_retry_limit` 호출 5곳, `ATTEMPT_LIMIT` | 삭제 | #949 |
| `agent.course` | `service.request_course` | `COURSE_LIMIT` 검사 삭제. run id를 먼저 만들고 run INSERT와 같은 트랜잭션에서 `charge(feature="course")` | #950 |
| `agent.course` | `execute_run` 실패 저장, `fail_stale_runs` | 결과 없이 끝난 run마다 `refund(feature="course")` | #950 |
| `reviews` | `PUT .../reviews/me` 신규 작성 | 같은 트랜잭션에서 `grant_review` | #951 |
| `auth.service` | `WITHDRAW_STEPS`, `MERGE_STEPS` | credits, reviews 추가 | #948, #951 |

추천 순서를 지키는 이유: 추천은 ②를 run INSERT보다 먼저 부르고, 그 사이 읽기 트랜잭션을 롤백한다(#208, #275). 그래서 확인(읽기) → 모델 → 저장과 차감(쓰기)이다. `Idempotency-Key` 재전송은 `_create_run`을 다시 타지 않으므로 이중 차감이 없다.

### import-linter (`backend/pyproject.toml`)

- `root_packages`와 기능 모듈 층에 `credits`, `reviews` 추가.
- 알려진 예외 1에 `auth.service -> credits.api`, `auth.service -> reviews.api` 추가.
- `credits.constants`를 다른 모듈이 import하면 `integration/test_import_rules.py`가 막는다(정상).

## 9. 결정 (#432, 2026-11-01)

| # | 결정 | 내용 |
|---|---|---|
| A | 게스트는 AI 추천과 코스를 쓰지 않는다 | 403 `GUEST_NOT_ALLOWED`. 카카오 전환을 권한다 |
| B | 후기 작성자 이름을 보이지 않는다 | `is_mine`만 내리고 화면이 「나」/「핑고 사용자」 |
| C | 공개 후기는 SNS가 아니다 | 같은 장소의 후기를 지도와 상관없이 보여 준다. 팔로우·댓글·프로필·피드 없음. 기획안 11절에 반영 |
| D1 | 후기 엔드포인트를 핀 id로 연다 | `Pin` 응답에 `places.id`를 새로 노출하지 않는다 |
| D2 | 새 모듈 `credits`, `reviews`와 import-linter 예외 | 위 8절 |
| D3 | `COURSE_LIMIT`, `RETRY_LIMIT` 삭제 | 폐지 예정으로 표시한 뒤 #954에서 지운다 |
| D4 | 응답의 `attempt_limit` 삭제 | 폐지 예정으로 표시한 뒤 #954에서 지운다. `attempt_no`는 유지 |
| D5 | 다시 찾기·근거 고치기는 상한 없이 무료 | 모델 비용은 ＋의 ②뿐이고 run당 글 10개로 묶인다 |
| D6 | 추천 환불 경로 | 없다(3.3). v1 추천은 실패하면 롤백한다 |
| D8 | 후기 숨김은 스크립트로만 | `reports.py`(신고 목록)와 `hide.py`. 자동 숨김 기준은 나중에 |

## 10. 리스크와 지켜볼 지표

| 리스크 | 지금의 대응 | 지표 |
|---|---|---|
| 후기 파밍(짧은 글로 크레딧 쌓기) | 한 장소 한 번 보상 | 사람당 하루 후기 수, 글 길이 분포 |
| 모델 비용(상한 제거) | 크레딧 소진 | `llm_calls` 사람당 하루 `cost_krw` |
| 후기란 품질(욕설, 비방) | 신고 + `reports.py` 확인 + 숨김 스크립트 | 신고 수, 숨김 수, 신고에서 숨김까지 걸린 시간 |
| 보상이 평점을 끌어올림 | 별점 무관 보상 + 사전 고지 | 첫 후기와 수정 후기의 평균 별점 차이 |

출시 전 법률 확인(자문 필요): 정보통신망법 권리침해 게시물 임시조치(요청을 받으면 지체 없이 — 신고를 매일 확인한다), 공정위 「추천·보증 심사지침」의 경제적 이해관계 표시(추천 탭 장소 광고와 겹치는 장소 포함).

## 11. 작업 분할

| 이슈 | 디렉토리 | 내용 | 먼저 있어야 하는 것 |
|---|---|---|---|
| 계약 PR | 루트 | 정본 문서, `CHANGELOG-api.md`, `contracts/` 타입·목 서버, 알려진 목록 | 9절 결정 |
| #948 | `backend/credits` | 모듈, 마이그레이션, `GET /credits/me`, 공유 파일 배선 | 계약 PR |
| #949 | `backend/recommend` | 확인·차감, `RETRY_LIMIT`·`ATTEMPT_LIMIT` 삭제 | #948 머지 |
| #950 | `backend/agent` (course) | 차감·환불, `COURSE_LIMIT` 삭제 | #948 머지 |
| #951 | `backend/reviews` | 모듈, 마이그레이션, 엔드포인트 4개, 보상, 신고·숨김 스크립트 | #948 머지 (`grant_review`) |
| #952 | `frontend` | 잔액·가격 표시, 402·403 안내, 상한 화면 정리 | 계약 PR (목 서버) |
| #953 | `frontend` | 핀 상세 후기 영역, 작성 시트, 신고, 별점 부품 | 계약 PR (목 서버) |
| #954 | 루트 | 폐지 예정 계약 삭제 | #949, #950, #952 |

#949·#950·#951은 서로 기다리지 않는다. #952·#953은 목 서버로 BE를 기다리지 않는다.

## 12. 완료 조건 (테스트)

credits
1. 계정이 없을 때 `GET /credits/me` = 30, 행이 생기지 않는다.
2. 첫 `charge`에 계정 생성 + `initial` +30 + `spend` -1 → 29. 동시 첫 호출 둘에도 `initial`은 한 번.
3. 잔액 0에서 `check_can_spend`, `charge` 모두 402, `detail = { required: 1, balance: 0 }`.
4. 게스트는 `check_can_spend`, `GET /credits/me` 모두 403(`detail.initial_credits = 30`), 계정 행 없음.
5. `refund` 두 번 → 한 번만 들어간다. 차감 없는 run의 `refund`는 False.
6. `grant_review` 같은 (user, place) 두 번 → 10, 0.
7. 탈퇴 → 계정·원장 없음. 합치기 → 게스트 쪽 행 없음.
8. 차감·환불·보상을 섞어 돌린 뒤 사람마다 `balance` = 원장 `delta` 합.

recommend
9. 잔액 0이면 `POST /maps/{mapId}/runs`가 402이고 ②가 불리지 않는다(`llm_calls` 0행).
10. 성공한 run 하나에 원장 `recommend_run:<run_id>` -1. 같은 `Idempotency-Key` 재전송은 차감이 늘지 않는다.
11. run 생성 중 예외(예: `NOT_READY`)면 차감도 없다.
12. 11번째 추천·다시 찾기·근거 고치기가 429 없이 통과한다.
13. 게스트의 `POST /maps/{mapId}/runs`는 403이고 ②가 불리지 않는다.

course
14. 6번째 코스 요청이 429 없이 통과한다(잔액이 있으면).
15. `ENGINE_ERROR`, `INTERRUPTED`로 끝난 run의 크레딧이 돌아오고, 두 번 끝내도 한 번만.
16. 게스트의 코스 요청은 403.

reviews
17. 별점 0·6, 공백 글, 501자 → 422. 500자 → 200.
18. 첫 저장 `credited = 10`, 수정 `credited = 0`, 삭제 뒤 다시 쓰기 `credited = 0`.
19. live 핀 → 422 `PLACE_NOT_SUPPORTED`. 비구성원 → 404(핀 조회와 같은 규칙).
20. 게스트 PUT·신고 → 403, 후기 행·신고 행·원장 없음.
21. 숨긴 후기는 목록·평균·개수·`mine`에서 빠진다.
22. 같은 장소를 가리키는 다른 지도의 핀에서도 같은 후기가 보인다.
23. 신고 두 번 → 204 둘, 행 하나. 내 후기 신고 → 422. 볼 수 없는 후기 신고 → 404.
24. 응답 어디에도 작성자 이름·사용자 id가 없다. 탈퇴한 사람의 후기는 남는다.
