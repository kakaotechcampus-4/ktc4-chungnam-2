# 루트 리뷰 가이드 — backend/auth

## 이번 작업 (이슈 #4 "로그인/로그아웃/탈퇴 API 구현")

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
