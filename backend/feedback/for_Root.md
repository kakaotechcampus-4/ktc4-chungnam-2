# feedback → 루트 보고 (#10 서비스 피드백)

작성: 2026-10-15 · 범위: `POST /feedback` 구현. 스펙은 `docs/api-spec.yaml`의 `FeedbackRequest`·`FeedbackReceipt`, `docs/data-model.md` feedback 절.

## 1. 한 줄 상태

`POST /feedback` 구현·단위 테스트·계약 테스트 완료. `KNOWN_MISSING`·`KNOWN_UNCOVERED`에서 `POST /feedback`을 지웠다.

## 2. 구현 구조 (`backend/feedback/`)

| 파일 | 역할 |
|---|---|
| `router.py` | `POST /feedback` → 201 `{id, created_at}`. 로그인만 필요. 순서: 검증(422) → 호출 상한(429) → 저장 (잘못된 요청이 상한을 쓰지 않는다) |
| `service.py` | `clean_message`(앞뒤 공백 제거 뒤 1~1000자), `submit`, `anonymize_by_user` |
| `api.py` | `check_submit_rate`, `anonymize_by_user` — 다른 모듈이 부르는 접점 |
| `models.py` | `feedback(id, user_id nullable, category, message, map_id nullable, created_at)`. FK 없음 |
| `schemas.py` | 스펙과 1:1. 알 수 없는 필드는 422, `category` 기본 `other` |

- `map_id`는 검사 없이 그대로 저장한다(구성원 여부·존재 여부 모두 안 본다). 빈 문자열은 NULL로 저장한다.
- 호출 상한은 사용자당 시간당 `FEEDBACK_PER_HOUR`(기본 10, 0 이하면 끔). places 검색과 같은 인메모리 슬라이딩 윈도라 프로세스를 다시 시작하면 초기화되고, 인스턴스가 여러 개면 각자 센다.

## 3. 공유 파일을 건드린 곳 (루트 확인 필요)

1. **`SlidingWindowLimiter`를 `places/ratelimit.py` → `common/ratelimit.py`로 옮겼다.** feedback이 places 내부 모듈을 import하면 모듈 경계 규칙(`api`·`schemas`만)에 걸려서다. `places/ratelimit.py`는 같은 이름을 다시 내보내는 한 줄짜리라 기존 import(places·integration 테스트)는 그대로 돈다.
2. **`auth/service.py::withdraw_user`**가 `feedback.api.anonymize_by_user`를 부른다(마지막 쓰기 단계, 같은 트랜잭션). 탈퇴자의 피드백은 `user_id`만 NULL로 끊고 내용은 남는다. 테스트: `auth/tests/test_service.py`.
3. **`common/settings.py`**: `feedback_per_hour` / `FEEDBACK_PER_HOUR`. `.env.example`에 주석으로 안내.
4. **`main.py`**: `feedback_router` include. **`alembic/env.py`**: `feedback.models` import.
5. **마이그레이션 `0031_feedback`** (`down_revision = 0030_agent_cursor_drop_gap_seq`, 작업 시작 시점의 head). 다른 마이그레이션 PR(⑤ 등)이 먼저 머지되면 그 뒤로 rebase해 `down_revision`과 파일 번호를 맞춘다.
6. **`agent/tests/test_migration.py`**: head가 0030이라고 못 박은 테스트(`test_head_is_agent_tables`)를 "head는 하나이고 agent 마이그레이션을 포함한다"로 바꿨다. 이후 다른 모듈의 마이그레이션이 붙어도 깨지지 않는다.

## 4. 알아 둘 점

- **스펙 PR #538(`docs/v2-notifications-feedback-470`)이 아직 develop에 없다.** 이 브랜치는 그 커밋(`5b1fe5b`)을 merge해서 스펙을 가져왔다. #538이 먼저 머지되면 이 PR의 diff에서 그 커밋이 빠진다. 이 PR을 먼저 머지하지 말고 #538 뒤에 머지한다.
- `KNOWN_*` 목록에서는 `POST /feedback` 두 줄만 지웠다. 알림함(#470) 줄은 notifications 구현 PR 몫이다.
- 피드백 내용은 사용자 입력이라 저장하지만 로그에는 남기지 않는다. 읽는 화면·API는 없다(운영이 DB에서 직접 본다).

## 5. 테스트

- `feedback/tests/test_service.py` — 공백 정리·길이 경계(1000자 허용, 1001자 거부)·익명화(다른 사용자 행은 그대로)
- `feedback/tests/test_router.py` — 401, 201 기본값, category·map_id 저장, 422 6종(저장 안 됨), 11번째 429(사용자별), 422가 상한을 쓰지 않음
- `integration/test_response_contract.py::test_feedback_responses_match_the_openapi_spec` — 201·401·422·429 응답이 OpenAPI 스키마와 맞는다
- `auth/tests/test_service.py::test_withdraw_user_detaches_feedback_author_but_keeps_content`
