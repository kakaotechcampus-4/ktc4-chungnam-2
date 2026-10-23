# 루트 리뷰 가이드 — backend/auth

## #694 사용자와 로그인 수단을 나누고, 게스트의 첫 카카오 로그인은 같은 사용자에 수단을 붙인다 (2026-10-24)

브랜치 `feat/user-identities-694`. 정본은 루트 워크트리 `docs/user-identities-694`의 data-model.md auth 절과 「게스트 전환과 합치기」
절이다(이 보고를 쓸 때 아직 커밋 전이라 이 브랜치의 docs에는 없다). FE 계약(api-spec.yaml) 변경 없음.
agent의 `reassign_user`는 로컬 브랜치 `feat/agent-reassign-user-694`(push 전)를 이 브랜치에 merge 커밋으로 합쳤다.

### 바뀐 것
- **모델·마이그레이션 `0039_user_identities`**(0038_place_hours 다음): `user_identities(id uuid, user_id → users.id, provider,
  provider_user_id, created_at)`, unique(provider, provider_user_id) `uq_user_identities_provider_identity`, unique(user_id, provider)
  `uq_user_identities_user_provider`. provider='kakao'인 users 행을 백필하고(created_at 유지) 같은 리비전에서 users의 provider,
  provider_user_id, is_guest와 `uq_users_provider_identity`를 지운다. downgrade는 수단을 users로 되돌리고, 수단이 없는 사용자는
  provider='guest', is_guest=true, provider_user_id=임의 uuid 문자열로 채운다(전환한 게스트는 카카오 사용자로 돌아간다).
- **is_guest 계산**: `User.is_guest`는 `column_property(NOT EXISTS user_identities)` — users를 읽는 같은 SELECT에서 계산한다.
  그래서 `CurrentUser.is_guest`, `GET /auth/me`, `auth.api.guest_user_ids`(maps의 후임 판정·방장 넘기기), maps의
  `creator_is_guest`(POST /maps 403)는 호출부 변경 없이 새 기준을 쓴다. 요청당 쿼리 수도 그대로다.
- **로그인 `find_or_create_user`**: 수단으로 사용자를 찾고, 없으면 사용자와 수단을 한 세이브포인트에서 만든다. 동시 첫 로그인은
  수단 유일 제약 위반이면 먼저 만든 사용자를 읽는다(세이브포인트와 함께 users 행도 되돌아간다). 탈퇴한 사용자는 지금처럼 막는다(#409).
  탈퇴해도 수단은 지우지 않는다(그게 막는 근거).
- **게스트 전환**(`service.claim_guest`, 콜백은 `login_guest_with_kakao_code`): 게스트 행을 FOR UPDATE로 잠그고
  - 그 카카오 수단이 없으면 게스트 행에 붙인다. 사용자 id·표시 이름 그대로, `guest_invite_token`은 비운다. 다른 모듈은 부르지 않는다.
    세션 쿠키는 같은 사용자라 게스트 때 것도 그대로 유효하다(콜백은 지금처럼 새 세션도 발급한다)
  - 있으면 지금의 `merge_guest_into`(MERGE_STEPS)로 옮긴다. `MERGE_STEPS`에 `("agent", agent_api)`를 마지막에 넣었다
  - 같은 카카오가 동시에 다른 게스트에 붙으면 뒤 요청은 수단 유일 제약에 걸려(세이브포인트만 롤백) 합치기로 간다
- **게스트 생성·상한·정리**: `join_as_guest`는 수단 없이 users만 만든다. 초대당 상한은 `guest_invite_token = 토큰 AND 수단 없음`으로,
  `purge_inactive_guests`는 수단 없는 사용자만 센다.
- **탈퇴 단계 목록**: `withdraw_user`의 모듈 호출을 `WITHDRAW_STEPS`(모듈 이름, fn(db, user_id, map_ids))로 바꿨다. 순서·동작은 그대로다.
  `test_withdraw_steps_are_also_merge_steps`가 "WITHDRAW_STEPS의 모듈 이름 ⊆ MERGE_STEPS의 모듈 이름"을 고정한다. 지도 잠금
  (`lock_member_maps`)은 단계가 아니라 맨 앞의 준비로 남겼다. auth 자신의 soft delete는 목록 밖이다(#452).

### 명세에 없어 정한 것
1. **같은 게스트로 겹친 콜백**: 뒤 요청은 잠금을 기다린 뒤 수단이 이미 붙은 것을 보고 보통 로그인으로 같은 사용자를 찾는다.
   이때 카카오 수단의 사용자가 그 게스트 자신이므로 `guest_merged=true`로 낸다("게스트 기록이 카카오 계정으로 이어졌다"와 같은 뜻).
2. **붙이기의 예상 밖 실패**(유일 제약 경합이 아닌 오류): 명세의 "어느 쪽이든 실패하면 로그인은 성공, guest_merged=false"를 따라
   보통 로그인으로 카카오 사용자를 새로 만들고 `false`. 게스트 기록은 남는다. 로그는 예외 종류만.
3. **잠근 뒤의 게스트 판정은 따로 읽는다**: 잠금을 기다린 SELECT의 하위 질의(`is_guest`)는 잠금 전 스냅숏을 봐서 앞 요청이 방금 붙인
   수단을 못 본다. 그래서 `_lock_live_guest`가 잠근 뒤 user_identities를 별도 문장으로 확인한다. 합치기도 같은 함수를 쓴다 —
   한 요청이 수단을 붙이는 사이 다른 요청이 같은 게스트를 다른 카카오 계정으로 합쳐 지우는 일을 막는다.
4. **이미 전환한 게스트의 세션으로 다시 로그인 시작**: 이제 게스트가 아니라 state에 게스트 id가 실리지 않고 보통 로그인이다.
5. **`user_identities.user_id` FK는 `ON DELETE CASCADE`**: 서비스에서 users는 탈퇴해도 soft delete라 CASCADE가 일어나지 않는다(수단은
   남는다). agent 테스트(`agent/tests/world.py`, `integration/test_agent_e2e.py`)와 `maps/tests/test_invites_api.py`가 정리 단계에서
   users 행을 실제로 지우는데, CASCADE 없이는 FK 위반으로 166개가 깨졌다. 테스트를 고치는 대신 스키마에 넣었다.

### 고친 테스트(다른 모듈 파일 포함, 테스트만)
- `auth/testing.py`에 `create_kakao_user`, `create_guest`, `make_guest`를 두고 `ensure_users`는 수단까지 만든다.
- `User(provider=..., provider_user_id=..., is_guest=...)`를 쓰던 곳: auth 테스트 5개, `integration/conftest.py`,
  `integration/test_guest_join.py`, `integration/test_permission_matrix_http.py`, `maps/tests/test_guest_limits.py`(is_guest를 켜던
  것을 `make_guest`로).
- `auth/tests/test_guest_merge.py`: 처음 전환(붙이기·다른 모듈 안 부름·이름 유지·토큰 비움·옛 쿠키 유효), 붙이기 실패, 같은 게스트로
  겹친 콜백, 같은 카카오로 겹친 붙이기(합치기로 감), 기존 카카오 계정으로 합치기, 탈퇴한 카카오 계정 거절.
- `auth/tests/test_user_identities_migration.py`: 백필, 두 유일 제약, 칸 삭제, downgrade 복원(전환한 게스트·새 게스트 포함), 다시 upgrade.
- `integration/test_guest_claim_e2e.py`를 두 갈래로 나눴다: 처음 전환(사용자 id·기록·멤버십 그대로, 지도 만들기 가능, 재로그인은 같은
  사람, 그 뒤 다른 게스트가 같은 카카오로 오면 합쳐짐)과 기존 카카오 계정으로 전환(B가 구성원/아님, agent 열람·코스 요청 포함 7개 모듈
  옮김, agent 단계 실패 시 전부 롤백).
- `integration/test_guest_join.py`: 수단을 붙인 게스트는 초대당 상한에서 빠지고, 게스트 정리 대상이 아니다.

### 루트 확인 필요
- docs(`data-model.md`·`api-spec.yaml`·`permissions.md`·CHANGELOG)는 루트 워크트리의 미커밋 변경 그대로다. 이 PR 전에 들어가야 한다.
- agent 쪽 루트 확인 요청 두 가지(코스 하루 상한, 겹친 진행 중 요청)는 `agent/for_Root.md` #694 절에 있다.
- 검증: `PINGO_TEST_DB=pingo_test_auth694 PLACES_MODE=dev LLM_MODE=dev python -m pytest` → 3351 passed, 24 failed, 1 xfailed,
  9 deselected. 실패 24개는 모두 이 PC venv에 `tzdata`가 없어 `ZoneInfo("Asia/Seoul")`가 실패한 것이다(agent/course 21개,
  `integration/test_agent_e2e.py` 1개, `integration/test_response_contract.py`의 코스 계약 1개와 그게 빠져 생긴 전체 덮기 검사 1개).
  agent 담당 보고(`agent/for_Root.md` #694)에 develop에서도 같다고 돼 있다. 이번 변경과 무관하다.
  `auth` 단독 139 passed(마이그레이션 테스트 포함).
- 복잡도: 예상 3, 실제 3.
- 디스코드 "#694 착수합니다"는 CLI로 못 남겼다.

---

## #560 게스트 → 카카오 전환, 기록 합치기 (2026-10-20) — 루트 확인 요청

스펙(`docs/api-spec.yaml`·`data-model.md`「게스트 합치기」)·마이그레이션 변경 없음. 새 엔드포인트 없음. 스펙 PR #657은 이미 develop에 머지돼 있다.

- **로그인 시작**(`GET /auth/kakao/login`): 세션 쿠키가 지금 살아 있는 게스트(서명·만료·탈퇴·로그아웃 무효화 모두 `get_current_user`와 같은 판정)의 것이면 그 id를 state 쿠키에 함께 서명해 넣는다. `state.발급시각.게스트id.서명` — 게스트 id는 서명 대상이라 바꾸거나 떼거나 붙이면 `invalid_state`. 게스트가 아니면 기존 3단 형식 그대로. `core.parse_state`(→`StateClaims`)가 추가됐고 `verify_state`는 그 래퍼다.
- **콜백**: state 검증 → 카카오 로그인 → state에 게스트 id가 있으면 `service.merge_guest_into`. 결과 `True/False`면 성공 리디렉션에 `guest_merged=true/false`, `None`이면 쿼리를 붙이지 않는다. 기존 `login_error` 처리·진입점 주소의 쿼리·조각 보존 규칙 그대로(같은 이름 `guest_merged`만 대체).
- **합치기**: 게스트 행을 `FOR UPDATE`로 잠그고 살아 있는 게스트인지 확인 → 세이브포인트 안에서 `MERGE_STEPS` 순서대로 `<module>.api.reassign_user(db, from_user_id=, to_user_id=)` → 마지막에 게스트 `deleted_at`. 어느 단계든 실패하면 세이브포인트만 롤백되고(카카오 사용자 생성은 유지) `guest_merged=false`, 로그는 `step=<이름> error=<예외 종류>`만.
- **`None`(쿼리 없음)이 되는 경우**: 게스트 행이 없거나 게스트가 아니거나 이미 삭제됨(이미 합쳐진 id 포함), 게스트 id와 카카오 사용자 id가 같음. 스펙의 "게스트 전환이 아닌 로그인에는 붙이지 않는다"를 합칠 대상이 없는 경우로 읽었다. 게스트가 로그인 도중 정리(90일)돼 사라진 드문 경우에도 쿼리가 없다 — FE가 `false`로 안내하길 원하면 알려 달라(`merge_guest_into`의 `None` 한 줄).

### 루트 확인 필요
1. **지금 develop에는 어떤 모듈에도 `reassign_user`가 없다.** `MERGE_STEPS`는 이름과 모듈 `api`만 등록하고 호출 시점에 함수를 찾는다 — 없으면 `AttributeError`로 그 합치기가 실패(`guest_merged=false`, 게스트 기록 유지). 일부 모듈만 옮기고 게스트를 지우는 일을 막으려는 선택이다. 즉 6개 모듈(maps·pins·recommend·shortlist·notifications·feedback)이 모두 병합되기 전에는 실제 전환이 항상 `false`다. 각 모듈 PR이 들어오면 auth 쪽은 코드 변경이 필요 없다.
2. **agent**: `data-model.md` 표에는 agent가 있지만 이번 지시의 목록에는 없어 `MERGE_STEPS`에 넣지 않았다. agent 담당이 `reassign_user`를 정하면 튜플 한 줄 추가.
3. 순서: maps(멤버십) → pins → recommend → shortlist → notifications → feedback. 모듈 간 순서 의존이 있으면(예: recommend가 maps 멤버십을 본다) 알려 달라.
4. 테스트는 `MERGE_STEPS`를 대역으로 바꿔 검증한다(`auth/tests/test_guest_merge.py`, `test_state_guest.py`). 실제 모듈이 합쳐진 뒤의 끝단 확인(`integration/`)은 각 모듈이 병합된 다음에 추가한다.
- 검증: `PINGO_TEST_DB=pingo_test_auth560 PLACES_MODE=dev LLM_MODE=dev python -m pytest auth integration/test_guest_join.py` → 142 passed. 전체 실행은 888 passed, 1 failed(`integration/test_response_contract.py::test_notification_responses_match_the_openapi_spec`) — 그 파일만 따로 돌리면 변경 전·후 모두 통과해 순서 의존으로 보이며 이번 변경과 무관.
- 복잡도: 예상 4, 실제 3.
- 디스코드 "#560 착수합니다"는 CLI로 못 남겼다(사람이 남겨야 한다).

---

## 이번 작업 (#369 2단계 auth 몫 — 방장 탈퇴 위임, 2026-10-07)

- `auth/service.py::withdraw_user`가 맨 먼저 `maps.api.transfer_or_delete_owned_maps(db, user_id)`를 부른다. 방장인 지도마다
  joined_at이 가장 빠른 구성원(탈퇴자 제외)에게 넘기고, 넘길 사람이 없으면 지도를 soft delete한다. 탈퇴자 멤버십 행은 member로
  강등만 하고 지우지 않는다(#245). 반응·근거 줄 삭제, users soft delete와 같은 트랜잭션이다. 스펙·마이그레이션 변경 없음.
- 위임 순서를 탈퇴 표시(`deleted_at`) 앞에 둔 이유: 후임 판정은 "탈퇴자 집합"을 읽는데 본인은 `user_id`로 따로 빠지므로 순서는
  결과에 영향이 없다. 실패 시 롤백 범위를 같게 하려고 첫 쓰기로 둔다.
- **다른 모듈 파일 수정**: `maps/service.py`(위임 시 `member.left` 발행), `maps/api.py`(docstring), `maps/tests/test_delete_leave_api.py`.
  내역은 `maps/for_Root.md` 맨 위.
- 테스트: `auth/tests/test_router.py::test_withdrawing_owner_hands_over_shared_map_and_deletes_solo_map` — `POST /auth/withdraw`로
  공유 지도는 후임이 owner·탈퇴자는 member로 남고 `member.left{map_id, user_id, new_owner_user_id}` 하나, 혼자인 지도는
  `map.deleted`만 나가고 404가 되는지 HTTP 끝단으로 확인.
- 검증: `PINGO_TEST_DB=pingo_test_auth369 PLACES_MODE=dev LLM_MODE=dev python -m pytest` → 1400 passed, 1 xfailed, 7 deselected,
  실패 2개는 `common/tests/test_settings.py`의 prod 기본값 테스트로 `LLM_MODE=dev`를 환경에 준 탓(빼고 돌리면 24 passed).
  작업 폴더에 pins 세션의 미커밋 변경(`pins/core.py`·`router.py`·`service.py`)이 같이 있는 상태에서 돌렸다.
- 복잡도: 예상 1, 실제 1.

---

## 이번 작업 (#160 탈퇴 연결, 2026-09-30)

- `auth/service.py::withdraw_user`가 `pins.api.delete_reactions_by_user`·`recommend.api.delete_evidence_lines_by_author`를 호출한 뒤 users를 soft delete한다(핀은 남김). 세 쓰기는 같은 트랜잭션이다. 스펙·마이그레이션 변경 없음.
- 테스트: `integration/test_withdraw_cascade.py` — 탈퇴 후 그 사용자의 반응·근거 줄이 사라지고(다른 사람 것은 유지), 핀 2개가 남으며, 탈퇴자 핀의 `created_by_display_name`이 "탈퇴한 구성원"임을 HTTP 끝단으로 확인.
- 검증: `PINGO_TEST_DB=pingo_test_auth python -m pytest` → 725 passed, 1 skipped, 0 failed.
- 이전 보고의 "완료하지 못한 것 1번(탈퇴 cascade)"은 이걸로 해소됐다. `reaction.changed` 이벤트는 발행하지 않는다(pins 함수 docstring 기준 — 탈퇴 시점 이벤트 정책이 필요하면 루트 결정).
- 디스코드 "#160 착수합니다"는 CLI로 못 남겼다(이전과 동일).

---

## 이번 작업 (#160 `PATCH /auth/me`, 2026-09-30)

`docs/api-spec.yaml` 시그니처 변경 없음 — 스펙 그대로 구현. 마이그레이션 없음.

- `PATCH /auth/me {display_name}` → `User`. 앞뒤 공백을 걷어낸 뒤 1~50자, 공백만/빈 값/51자/필드 누락은 422 `VALIDATION_ERROR`(기존 `RequestValidationError` 핸들러 그대로). 계정 단위 — `users.display_name` 하나를 고친다.
  - 판단 한 가지: 저장값은 **strip된 값**이다(`"  새이름 "` → `"새이름"`). 스펙은 공백 처리를 말하지 않아 "공백만은 불가" 지시를 앞뒤 공백 제거로 구현했다. 다르게 원하면 `schemas.UserUpdateRequest` 한 줄.
- `auth/api.py::display_names` — 탈퇴 사용자는 `"탈퇴한 구성원"`(`api.WITHDRAWN_DISPLAY_NAME`)을 돌려준다. pins·maps는 이 함수를 그대로 쓰므로 코드 변경 없음. **동작 변경**: 이전 테스트는 탈퇴자도 실명을 돌려주는 걸 요구했고 그걸 반대로 바꿨다(#155 결정 반영).
- `integration/test_spec_route_coverage.py` `KNOWN_MISSING`에서 `("patch", "/auth/me")` 삭제.
- 테스트: `auth/tests/test_router.py`(성공·strip·50자 경계·422 4종·401·탈퇴 후 401), `auth/tests/test_api.py`(탈퇴자 마스킹).
- 검증: `PINGO_TEST_DB=pingo_test_auth python -m pytest` → 619 passed, 1 skipped, 0 failed.

### 이번에 하지 않은 것 (지시대로 별도 PR)
- `withdraw_user`가 pins/recommend 삭제 함수를 호출하는 연결 — 그 두 함수가 develop에 들어온 뒤 별도 PR로 이어간다.

### 루트 확인 필요
1. **디스코드 "#160 착수합니다"** — CLI에서 디스코드에 글을 남길 수 없어 못 했다. 사람이 남겨야 한다.
2. **이슈 #160 본문 "실제 소요"** — 아래 "PR 작성 시" 메모 참고(기록했으면 채워져 있다).
3. `docs/CHANGELOG-api.md`에는 이미 `PATCH /auth/me`가 기록돼 있어 추가하지 않았다.

---

## 이전 작업 (이슈 #4 "로그인/로그아웃/탈퇴 API 구현")

`docs/api-spec.yaml`의 `/auth/kakao/callback`·`/auth/me`·`/auth/logout`·`/auth/withdraw` 4개
전부 구현 완료. `auth/deps.py::get_current_user`가 이미 `select()`로 dev/real을 고르는
배선이었으므로(PR #71), 그 "real" 자리를 채우는 방식으로 갔다 — 다른 모듈은 코드 변경 없이
그대로 동작한다(아래 "회귀" 참고).

### 만든/고친 파일

- `auth/models.py` (신규) — `users` 테이블(`docs/data-model.md` 10-16행)
- `auth/core.py` (신규) — 순수 함수만: 세션 토큰 서명/검증(HMAC-SHA256), 카카오 프로필에서
  표시 이름 추출
- `auth/service.py` (신규) — 셸: 카카오 토큰 교환·사용자 정보 조회(httpx), find-or-create,
  탈퇴(soft delete)
- `auth/deps.py` (수정) — `_real_get_current_user` 추가 + `select()`의 `"real"` 자리에 배선.
  `_dev_get_current_user`는 그대로 둔다(아래 이유)
- `auth/router.py` (신규) — `public_router`(`/kakao/callback`, 인증 의존성 없음) +
  `router`(`/me`,`/logout`,`/withdraw`, `dependencies=[Depends(get_current_user)]`)
- `auth/schemas.py` (수정) — `UserResponse` 추가(계약용, `api-spec.yaml`의 `User`와 1:1)
- `main.py` (수정) — 주석 처리돼 있던 `auth.router` import·include 두 줄을 실제로 채웠다
  (backend/CLAUDE.md "로컬 실행"이 각 모듈에게 명시적으로 허용한 지점)
- `alembic/env.py` (수정) — `import auth.models` 주석 해제
- `alembic/versions/0006_users.py` (신규) — `upgrade→downgrade→upgrade` 사이클 확인함
- `common/settings.py` (수정, 공유 파일) — `kakao_client_id`/`kakao_client_secret`/
  `kakao_redirect_uri`/`frontend_login_redirect_url` 4개 필드 추가. 전부 기본값 있음(`""` 또는
  `"/"`)이라 `common/tests/test_settings.py`·`test_adapter_assembly.py`의 기존 `Settings(...)`
  직접 생성 호출부를 깨지 않는다(실행해서 확인함 — 전체 회귀 참고). `__post_init__`에 새
  prod 가드는 추가하지 않았다 — 추가하면 `test_settings.py`의 여러 테스트가 기대하는
  `pytest.raises(..., match=...)` 메시지보다 이 체크가 먼저 걸려 깨진다(직접 확인함).
  카카오 키가 비어있으면 실제 로그인 시도 시점에 카카오 API가 400/401을 돌려주며 그때
  실패한다 — "설정 한 곳" 원칙은 지켰지만 "prod에 카카오 키가 없으면 부팅 자체를 막을지"는
  common 소유 파일의 새 검증 규칙이라 임의로 추가하지 않았다. 필요하면 결정 요청.
- `.env.example` (수정) — `FRONTEND_LOGIN_REDIRECT_URL=/` 추가

### 세션 설계 — DB에 세션 테이블 없음(data-model.md 그대로), 무상태 서명 쿠키

`SESSION_SECRET`으로 HMAC-SHA256 서명한 `user_id.발급시각.서명` 문자열을 `session` 쿠키(httpOnly,
`secure=prod에서만`, `samesite=lax`, 30일)에 그대로 넣는다. 매 요청마다 서명·만료를 확인한
뒤 **DB에서 그 user_id가 아직 탈퇴하지 않았는지 다시 확인**한다(`auth/tests/test_deps.py::
test_real_resolver_rejects_valid_signature_for_withdrawn_user`) — 쿠키만 보고 판정하면 탈퇴
직후에도 만료 전까지 계속 로그인 상태로 남는다.

### dev 스텁을 없애지 않은 이유

`_dev_get_current_user`(쿠키 문자열을 검증 없이 그대로 user_id로 받는 기존 스텁)는 그대로
남겨뒀다. `maps`·`pins`·`shortlist`의 기존 통합 테스트 전부가 이미 `cookies={"session":
"user_1"}` 형태로 이 동작에 의존한다(직접 확인 — 예: `maps/tests/test_invites_api.py`). 실제
서비스(prod)에서는 `Settings.__post_init__`이 `AUTH_MODE=dev`를 막으므로 안전하다.

### 회귀 확인

```
PINGO_ENV=test ./.venv/Scripts/python.exe -m pytest -q
```
→ **382 passed, 1 skipped(무관), 0 failed** (auth 37개 신규 포함). `alembic upgrade head` →
`downgrade -1` → `upgrade head` 사이클 확인. `AUTH_MODE=real`로 `import main` 시 실제로
`auth.deps._real_get_current_user`가 조립되는 것도 직접 실행해 확인함(`common.adapters.
format_assembly()` 출력 대조).

### `auth/mentor-review-plan.md`(PR #71) "루트 확인·결정 필요" 3번 해소

throwaway 앱이 아니라 `main.asgi_app` + 실제 등록된 `/auth/me`로 401 봉투를 확인하는 회귀
테스트를 추가했다(`auth/tests/test_router.py::test_missing_cookie_via_real_asgi_app_returns_envelope`,
`common/tests/test_errors.py::test_500_through_the_real_stack_has_cors_headers`와 같은 패턴).

## 완료하지 못한 것 — 루트 확인·결정 필요

### 1. [범위 관련, 최우선] 탈퇴 cascade 삭제 — `pins.reactions`·`recommend.evidence_lines`를 지우지 못했다

`auth/CLAUDE.md`가 지정한 삭제 범위 그대로다(범위 자체를 바꾸지 않았다 — 구현 방식만
아래처럼 막혔다):

- **`pins.reactions`**: `pins/api.py`(다른 모듈이 pins를 부르는 유일한 접점)에 사용자 단위
  일괄 삭제 함수가 아직 없다. 직접 확인함 — `create_ai_pin`/`mark_confirmed`/
  `unmark_confirmed`/`get_pin_for_viewer`/`get_pin_response_for_viewer` 5개뿐, `user_id`
  기준 삭제 함수는 없다.
- **`recommend.evidence_lines`**: 테이블 자체가 아직 없다. `recommend/models.py` 상단
  docstring이 명시적으로 "evidence_lines/regions/exclusions은 근거 조립·지역확인·재시도
  (이 세션의 후속 범위) 작업에서 추가한다"고 적어뒀다 — 지금 이 세션이 만들면 recommend
  세션이 실제로 쓰지 않을 스켈레톤을 미리 얼려두는 꼴이다.

**하지 않은 이유**: `backend/CLAUDE.md`("모듈 간 접근 — 함수/API로만")·`auth/CLAUDE.md`("이
모듈이 직접 그 테이블을 지우지 않는다")를 그대로 따르면, 이 두 함수는 각각 `pins`·`recommend`
세션이 만들어야 한다. `maps/for_Root.md`가 같은 상황(`auth/api.py::display_names` 등 필요)에서
직접 만들지 않고 루트에 필요한 함수 시그니처만 보고했던 전례를 그대로 따랐다.

**필요한 함수(시그니처 제안, 최종 결정은 그 모듈 담당)**:
```python
# pins/api.py
def delete_reactions_by_user(db: Session, *, user_id: str) -> int: ...  # 삭제 건수 반환

# recommend/api.py (신규 파일 — evidence_lines 테이블이 생긴 뒤)
def delete_evidence_lines_by_author(db: Session, *, user_id: str) -> int: ...
```
두 함수가 생기면 `auth/service.py::withdraw_user` 안에서 호출 두 줄만 추가하면 된다(함수
docstring에 이미 이 위치를 표시해뒀다). **완료 정의의 "연결된 데이터가 실제로 지워지는지
테스트"는 이 두 함수가 없는 한 지금은 만들 수 없다** — `auth/tests/test_service.py`는 현재
`users` 행 soft delete까지만 검증한다.

### 2. 로그인 성공 후 리다이렉트 URL — FE 오리진의 정본이 없다

`maps/for_Root.md` "초대 링크 URL" 항목과 같은 갭이다. 지금은 `FRONTEND_LOGIN_REDIRECT_URL`
환경변수(기본값 `"/"`, 상대경로)로 두고, 실제 카카오 로그인 성공 후 302 리다이렉트도 이
값을 그대로 쓴다. FE 배포 도메인이 정해지면 `.env`에 절대 URL로 채우면 된다 — 코드 변경
불필요.

### 3. `docs/api-spec.yaml`의 `/auth/kakao/callback` — `security: []` 여전히 미반영

PR #71 때 이미 보고했던 항목을 재확인함 — `docs/api-spec.yaml:28-38`에는 아직 `security: []`가
없다(`mentor-review-plan.md`가 "이미 확정됨"이라 적었던 것과 다름, 이전 for_Root.md 1번 참고).
`docs/api-spec.yaml`은 손대지 않았다(auth/CLAUDE.md "넘지 말 것" — 스펙은 루트만 고친다) —
대신 `auth/router.py`에서 `/kakao/callback`을 인증 의존성이 없는 별도 라우터(`public_router`)에
둬서 **실제 동작은 스펙 의도대로** 맞췄다. YAML 자체를 고칠지는 루트 판단.

### 4. FK 백필 — `users.id`를 참조하는 모든 String 컬럼

`maps.created_by`/`memberships.user_id`/`invites.created_by`(`0005_maps.py`), `pins.created_by`/
`reactions.user_id`(`0001_pins.py`), `recommend_runs.requested_by`(`0003_...py`) 전부 "users(id)
— auth 도착 시 FK"라는 주석과 함께 String으로 유보돼 있었다. FK 추가는 이번 리비전 범위
밖이다 — 각 모듈의 기존 dev 값("user_1" 등)이 실제 `users.id`(UUID 문자열)와 다르므로, FK를
걸기 전에 데이터 백필 또는 truncate 결정이 먼저 필요하다(`0005_maps.py`가 같은 이유로 남긴
것과 동일한 성격).

### 5. 탈퇴한 계정으로 재로그인 시도 — 지금은 막기만 한다

`find_or_create_user`가 `deleted_at is not None`인 기존 계정을 발견하면 조용히 되살리지 않고
`UNAUTHORIZED`로 막는다. "탈퇴 계정 재활성화를 허용할지"는 12절 범위 밖의 별도 정책 결정이라
임의로 정하지 않았다 — 필요하면 루트 확인 후 `find_or_create_user`에 분기 하나만 추가하면 된다.

### 6. `common/tests/test_adapter_assembly.py` — 건드리지 않았지만 주석이 약간 stale해졌다

`MISSING_REAL = {"pins.PlaceGateway": "#34", "auth.SessionResolver": "#4"}`의 주석("실구현이
아직 없는 포트 목록")이 이제 `auth.SessionResolver`엔 정확히 맞지 않는다(real 구현이 생겼다) —
다만 이 딕셔너리는 실제로는 "포트 이름 전체 인벤토리" 검사에 쓰이고(대조: `assembly()`가
반환하는 포트 집합과 키 집합을 비교), `auth.SessionResolver`는 `AUTH_MODE=dev`인 테스트
환경에서도 여전히 `select()`를 거쳐 등록되므로 **삭제하면 오히려 이 테스트가 깨진다**(직접
실행해 확인함). 그래서 이번엔 손대지 않았다 — PR #71 때와 달리 기능적으로 필요한 변경이
아니라서다. 주석만 정정할지는 사소한 사항이라 루트 판단에 맡긴다.

---

# 루트 리뷰 가이드 — backend/auth (PR #71 멘토 리뷰 대응, 이전 작업)

`backend/pins/for_Root.md`(#16·#17)와 같은 형식.

## 구현 범위

- `auth/schemas.py::CurrentUser` — 인증이 만들어내는 유일한 산출물(지금은 `user_id`뿐)
- `auth/deps.py::get_current_user` — 인증이 필요한 모든 모듈이 라우터 선언
  (`APIRouter(dependencies=[Depends(get_current_user)])`)에서 가져다 쓰는 단일 진입점
- 멘토 코멘트 4("router마다 세션 해석을 반복하지 말고 middleware 같은 것으로 균일하게") 대응 —
  ASGI 미들웨어가 아니라 FastAPI 라우터 `dependencies=[...]`로 구현(근거는 `mentor-review-plan.md`
  "결정" 절 참고: SSE 버퍼링 전례에 대한 신중함, DI 필요성, 테스트 오버라이드 편의, OpenAPI
  `security` 선언과의 자연스러운 대응)
- `auth/tests/test_deps.py` — 3개 테스트 전부 통과 (`pytest auth/tests -q`)
- **선행 조건 확인**: `backend/common/`의 `common.errors.AppError`·`register_error_handlers`가
  실제로 이 리포에 존재하고 시그니처가 계획서에 적힌 그대로임을 직접 읽어 확인한 후 착수함
  (`AppError(code, message=None, detail=None)`, `main.py`가 이미 `register_error_handlers(app)`
  호출 중, `asgi_app`도 이미 있음)
- **후속 gap 대응 — `get_current_user`를 `common.adapters.select()`로 재배선** (멘토 코멘트 6
  — "검증 없는 쿠키 스텁이 PINGO_ENV=prod에서도 그대로 돌아갈 수 있다" 대응). 자세한 내용은
  아래 "select() 재배선" 절 참고.

## 꼭 읽어야 할 것 (판단이 들어간 곳)

1. **이 파일 아래 "루트 확인·결정 필요" 항목들.**
2. **`auth/deps.py::get_current_user`** — 이 계획 전체의 핵심 전제가 "의존성 단계에서 던진
   `AppError`가 앱 레벨 핸들러에 잡히는가"다. `test_missing_cookie_via_http_returns_envelope`가
   이걸 실제로 증명한다(throwaway 앱이지만) — `backend/pins/deps.py`가 세웠던 "라우터의
   try/except를 우회한다"는 전제가 이제 깨졌다는 뜻이고, 그래서 `pins/deps.py`의 옛 인증 함수
   (`get_current_user_id`/`require_user_id`)는 이 파일의 존재로 대체 대상이 된다(삭제는
   `pins/mentor-review-plan.md`가 별도 PR에서 수행).
3. **"사용 규약" 절** — 다른 모듈(authz, pins, 향후 maps 등)이 이 의존성을 라우터 `dependencies=`
   선언에 걸어야 멘토가 지적한 문제가 실제로 해소된다. 개별 엔드포인트 함수 안에서 다시
   불러쓰면(예: `viewer_id: CurrentUser = Depends(get_current_user)`만 하고 라우터 레벨
   `dependencies=`는 생략) 인증 자체는 되지만 "라우터 선언 하나로 전체를 건다"는 목표는
   달성되지 않는다 — 각 모듈 PR 리뷰 시 이 점을 확인해야 한다.

## select() 재배선 (후속 — 처음 구현 완료 뒤 추가로 발견·수정한 gap)

**gap**: `get_current_user`가 `common.adapters.select()`를 전혀 거치지 않고 `def`로 직접
정의돼 있었다. `common/settings.py`의 `_PORTS`에는 `"auth"`가 이미 있어(`auth_mode` 필드도
있음) `PINGO_ENV=prod`에서 `AUTH_MODE=dev`를 **명시**하면 `Settings.__post_init__`이 막아주지만,
`AUTH_MODE`를 안 정하거나 `AUTH_MODE=real`을 정한 경우엔 (prod 기본값이 `real`이라 보통 이쪽이다)
`Settings()` 생성 자체는 통과한다 — 그런데 `get_current_user` 코드는 `settings.auth_mode`를
아예 참조하지 않고 있어서, 실제로는 검증 없는 쿠키 스텁이 "real 모드"라는 이름표를 달고
그대로 돌아가는 상태였다. 즉 **설정값과 실제 동작이 분리돼 있었다** — 이게 멘토 코멘트 6이
우려한 정확한 그 상황이다.

**조치**: `_dev_get_current_user`로 이름을 바꾸고, `select()`로 재배선했다(`pins/deps.py::
get_place_gateway`, `authz/deps.py::get_membership_gateway`와 같은 패턴). `CurrentUserDep`·
바깥에 노출되는 이름(`get_current_user`)은 안 바뀌어서 `pins`·`authz` 쪽 import는 무수정으로
계속 동작한다.

## 루트 확인·결정 필요 (PR #71 당시, 이제 대부분 해소됨)

1. ~~`docs/api-spec.yaml`의 `/auth/kakao/callback`에 `security: []`가 없다~~ — 이번 작업에서
   재확인함, 위 "이번 작업" 3번 참고(여전히 미반영, 라우터 배선으로 실제 동작만 맞춤).
2. ~~"잘못된 쿠키" 케이스 미검증~~ — 이번 작업(`_real_get_current_user`)으로 해소.
   `auth/tests/test_deps.py`의 서명 위조·만료 테스트 참고.
3. ~~회귀 테스트가 throwaway 앱만 태운다~~ — 이번 작업으로 해소, 위 "이번 작업" 참고.
4. (해소됨) `authz`·`pins` 세션 알림 절차 — `pins/router.py`·`authz/guard.py`가 이미 이 파일을
   쓰고 있어 실제로 알릴 필요가 없었다.
5. `pins`와의 순서 의존 — `pins`가 이 의존성 적용과 `pins/deps.py`의 옛 인증 함수 삭제를 같은
   PR로 묶었는지는 `pins` PR 리뷰 시 확인 필요(auth 세션이 확인할 수 있는 범위 밖).

## 환경 이슈 (auth와 무관, 참고용)

`backend/.venv`가 준비돼 있고 전체 의존성이 설치돼 있어 이번 작업도 같은 가상환경에서
문제없이 진행함(`./.venv/Scripts/python.exe`).

## 로그아웃 토큰 무효화 (0014, 2026-09-30) — 루트 조치 요청

### 루트가 해야 할 일
1. **`docs/data-model.md` users 항목에 `sessions_valid_after` 추가**:
   `users(..., deleted_at, sessions_valid_after timestamptz NULL)` — "로그아웃 시각. 이 시각 이전(같은 초 포함)에 발급된
   세션 토큰은 무효. NULL이면 전부 유효". 문서는 루트 소관이라 auth가 고치지 않았다. 지시는 "루트 보고 → 마이그레이션" 순서였으나
   정의가 명확해 구현을 먼저 했다 — 루트가 다른 정의를 주면 `0014`를 그에 맞춰 고쳐야 한다.
2. **git 저장소 밖에서 작업함**: 이 작업 디렉토리는 git 저장소가 아니어서 develop pull·브랜치·develop merge·PR을 하지 못했다.
   이슈 번호도 받지 못해 디스코드 "#N 착수합니다"와 이슈 "실제 소요" 기록이 남아 있다. 변경 파일은 아래 목록 그대로 PR로 올리면 된다.
3. 마이그레이션 번호 0014가 다른 PR과 겹치면 먼저 머지된 쪽이 우선(`backend/CLAUDE.md`).

### 변경 내용 (API 시그니처 `docs/api-spec.yaml` 변경 없음)
- `auth/models.py`: `users.sessions_valid_after` 추가. `alembic/versions/0014_users_sessions_valid_after.py` (0013 다음, 빈 DB에서 `upgrade head` 통과 확인).
- `auth/core.py`: `parse_session_token`이 `SessionClaims(user_id, issued_at)`을 반환(기존엔 user_id 문자열), 순수 함수 `is_revoked` 추가.
- `auth/deps.py`: `_real_get_current_user`가 기존 users 조회 결과로 무효화 여부를 판정 → 401 UNAUTHORIZED. 쿼리는 늘지 않음.
- `auth/service.py`: `revoke_sessions` 추가(UPDATE라 행이 없는 dev 스텁 사용자도 실패 안 함). `auth/router.py`: `/auth/logout`이 호출.
- 테스트: `test_core.py`, `test_deps.py`, `test_service.py`에 추가(로그아웃 전 토큰 401 / 이후 발급 토큰 정상 / 탈퇴 사용자 401 유지).

### 검증 결과
- auth 테스트 전부 통과. backend 전체: 602 통과, **3 실패** — `realtime/tests/test_router_integration.py` 2건,
  `realtime/tests/test_shutdown.py` 1건. auth를 제외하고 돌려도 동일하게 실패하고 realtime 단독은 통과 → 이번 변경과 무관한
  공유 테스트 DB(`pingo_test`) 모듈 간 간섭으로 보인다(git이 없어 변경 전 기준선 비교는 못 함). realtime 담당 확인 필요.
- 참고: `pingo_test`에 옛 users 테이블이 남아 있어 새 컬럼이 없다고 실패했고, DB를 한 번 삭제해 재생성했다
  (`create_all`은 기존 테이블을 ALTER하지 않음). 다른 사람 로컬 테스트 DB도 같은 증상이 나올 수 있다.

### 알려진 한계
- 토큰 발급 시각이 초 단위라 로그아웃과 같은 초에 발급된 새 토큰도 거절된다(`<=` 비교, 보수적 선택 — 카카오 왕복 때문에 사실상 발생 안 함).
- #160(PATCH /auth/me, 탈퇴 연결)은 PR #156 머지 뒤 별도 PR — 이번에 하지 않음.

## #126 — PINGO_ENV 기본값 prod, 인증 스텁·AUTH_MODE 제거 (2026-10-02) — 루트 확인 요청

### 루트가 확인·갱신할 것 (루트 소관이라 손대지 않았다)
1. **`docs/openapi-workflow.md` 5절 표**: `AUTH_MODE | real | ...` 행을 **삭제**해야 한다(환경변수가 없어졌다). 그 아래
   "`PINGO_ENV`를 dev로" 문구(104행 트러블슈팅)는 여전히 맞다. 5절 `backend/.env`에 `PINGO_ENV=dev`를 한 줄 적도록
   표에 추가하는 것을 권한다 — 이제 안 적으면 prod 가드가 돌아 로컬 서버가 `ConfigError`로 안 뜬다.
2. **`backend/.env.example`**: 이번 PR에서 갱신 완료(`AUTH_MODE` 줄 삭제, `PINGO_ENV` 기본값 설명). 로컬 `.env`에 남은
   `AUTH_MODE=dev`는 무시되므로 지워도 되고 안 지워도 된다.
3. **배포 설정(Cloud Run 등)**: `PINGO_ENV`를 빠뜨리면 이제 prod로 뜬다 — 의도한 동작이지만, prod 가드(SESSION_SECRET·
   FRONTEND_BASE_URL·CORS_ALLOW_ORIGINS·PLACES_MODE=real·LLM_MODE=real)를 채우지 않은 환경은 기동 단계에서 멈춘다.
   `PLACES_MODE=real`은 places 실구현이 있어야 하니 배포 전 확인이 필요하다.
4. `PINGO_ENV` 없이 `alembic`·시딩 스크립트 등 `common.settings`를 import하는 CLI를 돌리던 사람은 같은 가드에 걸린다
   (로컬은 `.env`의 `PINGO_ENV=dev`가 `load_dotenv`로 읽혀 영향 없다).

### 변경 내용 (API 시그니처 `docs/api-spec.yaml` 변경 없음)
- `common/settings.py`: `PINGO_ENV` 기본값 `prod`, `auth_mode` 필드·`AUTH_MODE`·`_PORTS`의 `auth` 제거.
- `auth/deps.py`: `_dev_get_current_user`·`select()` 제거, `get_current_user`가 서명 쿠키 검증 구현 하나.
- `auth/testing.py`(신규): `session_cookie(user_id)`(서명된 토큰), `ensure_users(db, *ids, display_names=)`.
  `maps`·`pins`·`shortlist`·`recommend`·`integration` 테스트가 이걸로 로그인한다(각 conftest의 `app_client`가 사용자 행을 만든다).
  `realtime`·`authz`·`places` 테스트는 스텁에 기대지 않아 바꿀 게 없었다.
- `auth/service.py::find_or_create_user`: 동시 첫 로그인 — 세이브포인트 안에서 INSERT, `23505` + `uq_users_provider_identity`일 때만
  기존 행을 재조회(탈퇴 행이면 거절). 이슈가 말한 `add_item`과 달리 `db.add`를 세이브포인트 **안**에서 하고 `db.rollback()`은 부르지 않는다 —
  밖에서 add하면 `begin_nested()` 진입 시 autoflush가 세이브포인트 밖에서 터지기 때문이다(`shortlist/service.py::add_item`이
  `db.rollback()`을 부르는 이유로 보인다. 이쪽은 손대지 않았다).

### 테스트 의미가 바뀐 곳
- users 행이 있어야 로그인되므로 "users 행이 없는 구성원은 `display_name` 키가 없다"는 maps 테스트는 구성원 응답이 `{user_id, display_name}`이라는
  단언으로 바꿨고, "초대자 행 없음 → 탈퇴한 구성원" 테스트는 초대 생성 뒤 행을 지우는 방식으로 만든다.
- `pins/tests/test_permissions_contract.py::test_get_pins_non_member_is_404`는 `app_client` 없이 실제 DB로 나가던 것을 `app_client`를 쓰게 했다.

### 검증
- backend 전체 949개 통과(변경 전 946개 + 신규 3개).
- 동시 첫 로그인 테스트는 "두 요청이 둘 다 없다고 본 순간"을 첫 조회만 비우는 방식으로 재현한다. 두 커넥션을 실제로 경쟁시키는 테스트는 아니다.

## #128 — 카카오 로그인 OAuth state 검증 (2026-10-02) — 루트 조치 요청

백엔드(이슈 할 일 2·3)를 구현했다. **`docs/api-spec.yaml`은 건드리지 않았다** — 아래는 루트가 먼저 정리해야 할 스펙·문서·FE 쪽이다.
이 PR은 #126 PR(#213) 위에 쌓여 있다(테스트가 `auth.testing`을 쓴다). #213이 머지되면 base가 `develop`으로 바뀐다.

### 루트가 해야 할 일
1. **스펙에 `GET /auth/kakao/login` 추가** (`tags: [auth]`, `security: []`, 응답 `302` — 카카오 인가 화면으로, `Set-Cookie: kakao_oauth_state`).
   구현은 이미 `auth/router.py::get_kakao_login`에 있다. 카카오 설정(`KAKAO_CLIENT_ID`·`KAKAO_REDIRECT_URI`)이 비어 있으면 `500 INTERNAL_ERROR`.
2. **`/auth/kakao/callback`에 `state` 쿼리 파라미터 추가.** 코드는 없으면 거절로 처리하므로 스펙에서는 `required: true`가 맞다
   (FastAPI에서 `Query(...)`로 두면 빠졌을 때 `VALIDATION_ERROR` 422가 되어 이슈의 "state가 없다 → 거절" 단일 응답과 달라져 `Optional`로 두고 401로 통일했다 — 스펙을 required로 쓰더라도 구현은 그대로 맞다).
   `401` 응답을 스펙에 적어야 한다: `{code: UNAUTHORIZED, detail: {reason: "invalid_state"}}`.
3. **`docs/CHANGELOG-api.md`에 먼저 기록하고 프론트에 알린다.** 프론트 변경점:
   - `frontend/src/features/auth/auth.ts::kakaoLoginUrl()`이 지금 카카오 인가 URL을 직접 만든다(이슈 본문의 "만드는 곳이 없다"와 다르다).
     `{백엔드}/auth/kakao/login`으로 이동하게 바꿔야 한다. 직접 만든 URL로 가면 `state`가 없어 콜백이 **항상 거절**된다 — BE가 먼저 머지되면 로그인이 깨지므로
     **BE·FE를 같은 시점에 배포**하거나 FE를 먼저 바꾼다.
   - `contracts/`(msw 목 서버)에 `/auth/kakao/login` 추가.
4. **에러 코드**: 새 코드 없이 기존 `UNAUTHORIZED`(401)에 `detail.reason = "invalid_state"`로 거절한다. `docs/errors.md`에 `detail.reason` 규약을 적을지 판단 필요.
5. **UX 결정 필요**: 콜백은 브라우저의 최상위 이동이라 거절되면 사용자가 JSON 에러 봉투를 그대로 본다(기존 카카오 실패 경로도 같다). FE 로그인 화면으로
   `?error=...`와 함께 돌려보낼지는 루트 결정 — 이번엔 이슈대로 "로그인을 거절"만 했다.

### 구현 요약
- `auth/core.py`(순수): `new_state`, `create_state_cookie_value`/`verify_state`(서명 대상에 용도 문자열 `kakao_oauth_state:`를 넣어 세션 토큰과 서로 대체 불가, 상수 시간 비교, TTL 10분), `kakao_authorize_url`.
- `auth/router.py`: `/auth/kakao/login`이 state 쿠키(`kakao_oauth_state`, HttpOnly, SameSite=Lax, prod에서 Secure, Path=`/auth/kakao`, 10분)를 심고 302.
  콜백은 카카오 호출 **전에** state를 검증하고, 성공·실패 모두 쿠키를 지운다(실패 때는 예외 대신 같은 에러 봉투 응답을 만들어 쿠키 삭제를 실어 보낸다).
- 쿠키는 **백엔드 오리진**에 붙는다 — 로그인 시작(`/auth/kakao/login`)과 콜백(`KAKAO_REDIRECT_URI`)이 같은 호스트여야 한다(로컬은 `localhost`로 통일, `openapi-workflow.md` 5절과 같은 주의).
- 테스트 72개(auth): 다른 브라우저의 콜백 링크 거절, 같은 링크 두 번째 거절, state 누락·불일치·서명 위조·만료, 정상 흐름, 실패 시에도 쿠키 삭제, state 쿠키가 세션으로 통하지 않음. state 검증을 끄면 7개가 실패하는 것을 확인했다.

## #315 — 카카오 콜백 실패를 진입점으로 돌려보내기 (2026-10-04) — 루트 확인 요청

계약(`docs/api-spec.yaml` `/auth/kakao/callback`, CHANGELOG 2026-10-04 두 번째)대로 구현했다. 스펙·docs는 건드리지 않았다.

### 루트가 판단할 것
- **탈퇴한 계정으로 로그인하면** 스펙의 `login_error` 4개 값 어디에도 맞지 않는다(카카오 실패도 서버 오류도 아님). 지금은 `server_error`로 보낸다. FE가 "탈퇴한 계정입니다"를 따로 보여 주려면 값(예: `withdrawn`)을 스펙에 추가해야 한다.
- 스펙 `login_error` 설명은 구현과 일치한다. 다만 `code`가 비어 있으면(빈 문자열) `cancelled`로 본다 — 스펙 문구("code가 없음")의 연장이다.

### 구현 메모
- 순서: state 검증 → `error` 쿼리·`code` 없음(`cancelled`) → 카카오 호출. 위조된 요청에는 카카오를 부르지 않고, state가 틀리면 `error`가 붙어 있어도 `invalid_state`다.
- `service.KakaoApiError`(AppError 하위, `UNAUTHORIZED`): 카카오 HTTP 비200·네트워크 오류·JSON 아님·`access_token`/`id` 누락. 콜백이 `kakao_failed`로 돌려보내는 근거다. 그 밖의 예외는 `server_error`(세션 롤백 후)이고 로그에는 예외 **종류**만 남긴다(응답 본문·토큰·예외 메시지 금지).
- 기존 쿼리가 있는 진입점 주소는 보존하고 같은 이름의 `login_error`만 대체한다.
- `/me`의 "이중 조회"는 같은 요청 세션의 identity map에서 나와 SQL이 한 번만 나간다(`get_db_session` 캐시) — 바꾸지 않았다.
- FE: `login_error` 값별 안내는 FE 몫이다. 목 서버(`contracts/mocks/handlers/auth.ts`)가 실패 경로를 흉내 내는지는 루트 확인.

## #472 PR 1 — 게스트 기반 (2026-10-16) — maps가 부르는 법

스펙·docs는 건드리지 않았다. 마이그레이션 `0035_users_guest`(head): `users.is_guest`(not null, 기본 false)·`guest_invite_token`(인덱스)·`last_seen_at`. `provider`는 text라 `'guest'` 값에 DDL이 필요 없다.

- **지도 만들기 차단(`POST /maps` → 403 `GUEST_NOT_ALLOWED`)**: 라우터에서 `user.is_guest`를 본다. `CurrentUser.is_guest: bool = False`는 세션 인증(`auth.deps.get_current_user`)이 users 행에서 채운다. 기본값이라 `CurrentUser(user_id=...)`를 직접 만드는 기존 코드·테스트는 그대로다(그 경우 게스트가 아닌 것으로 본다).
- **후임 판정·방장 넘기기 대상 검사**: `auth.api.guest_user_ids(db, user_ids) -> set[str]`. `withdrawn_user_ids`와 같은 배치 조회(빈 입력은 쿼리 없이 빈 집합, users 행 없는 id는 게스트가 아님). 후보 id 목록을 한 번에 넘겨 `candidates - guest_user_ids(...) - withdrawn_user_ids(...)`로 거른다.
- `GET /auth/me`·`PATCH /auth/me` 응답에 `is_guest`(bool)를 항상 포함한다.

## #472 PR 2 — POST /auth/guest (2026-10-16)

스펙·docs는 건드리지 않았다. 구현: `auth/router.py::post_guest`(public_router, `security: []`), `auth/service.py::join_as_guest`·`purge_inactive_guests`, `auth.api.purge_inactive_guests(db, now, older_than_days=90)`.

- 흐름(한 트랜잭션): IP 상한 → 이름 검증(422) → `maps.api.check_invite`(404·410) → 토큰 단위 advisory lock → 게스트 수 확인(409 `GUEST_LIMIT`, `users.guest_invite_token`으로 셈, 탈퇴한 게스트도 센다) → users 행 생성(`provider='guest'`, 임의 `provider_user_id`) → `maps.api.accept_invite`(member.joined·방장 알림 포함) → 세션 쿠키(카카오 로그인과 같은 쿠키, 30일) → 201 `{user, map}`.
- 상한: 토큰당 게스트 10명, IP당 시간당 10회(성공·실패 모두 셈, `common.ratelimit`, 인메모리라 인스턴스마다). IP는 `request.client.host`다 — Cloud Run 앞단에서 프록시 주소로 보이면 uvicorn `--proxy-headers`/`forwarded_allow_ips` 설정이 필요한지 루트 확인.
- `last_seen_at`: 게스트의 세션 인증 때 하루 한 번만 갱신(`auth/deps.py`). 일반 사용자는 쓰지 않는다.
- 정리: `purge_inactive_guests`는 `last_seen_at`(없으면 `created_at`)이 90일 지난 게스트를 `withdraw_user`로 지운다(일반 탈퇴와 같은 연쇄, soft delete). 호출 연결은 #168. 탈퇴한 게스트의 알림 삭제·멤버십 유지는 `integration/test_guest_join.py`로 확인.
- 로그에는 쿠키·초대 토큰·이름을 남기지 않는다(새 로그 없음).
- **maps 몫(이 PR에서 하지 않음)**: `POST /maps`의 게스트 403 `GUEST_NOT_ALLOWED`, 후임 판정·방장 넘기기 대상(422 `OWNER_TARGET_INVALID`)에서 `auth.api.guest_user_ids`를 쓰는 것.
- `maps/api.py`에 위임 함수 2개 추가(루트 승인): `check_invite`, `accept_invite`. maps 로직(service·core·router)은 건드리지 않았다.
