# 루트 리뷰 가이드 — backend/common (PR #71 멘토 리뷰 대응)

`backend/pins/for_Root.md`(#16·#17), `backend/authz/for_Root.md`(#36)와 같은 형식.
이 작업은 `common/mentor-review-plan.md`(파일 상단에 "루트 담당"이라고 이미 적혀 있음)를
그대로 실행한 것이다 — 계획 자체가 DeepSeek 1·2차, Antigravity 검수를 거쳐 확정된 상태였고,
이번 세션은 그 문서를 검증까지 포함해 그대로 구현했다.

## 구현 범위

PR #71 멘토 리뷰 3건 대응:
- **코멘트 4 (500에 CORS 헤더 누락)**: `main.py`가 `CORSMiddleware`로 앱 전체를 바깥에서 감싸는
  `asgi_app`을 노출. 실행 명령이 `uvicorn main:app` → `uvicorn main:asgi_app`로 바뀐다.
- **코멘트 6 (개발용 스텁이 운영에 흘러들어갈 수 있는 구조)**: `common/settings.py`(환경+어댑터
  모드 단일 소스) + `common/adapters.py`(`select()`를 거치지 않으면 어댑터를 못 얻는 구조,
  prod에서 dev 스텁이 섞이면 `ConfigError`로 부팅 자체를 거부) + `common/contracts.py`(dev/real
  구현이 같은 시그니처를 지키는지 보는 계약 테스트 뼈대, 아직 실사용처 없음 — 아래 참고).
- **코멘트 5 (이벤트 발행이 커밋 후 별도로 일어나 상태 불일치 가능)**: `common/events.py`
  이벤트 아웃박스(`EventLog` 테이블 + `record_event()`) — 상태 변경과 같은 트랜잭션에 이벤트
  행을 남기고, 실제 전달(realtime)은 커밋된 로그를 읽어 재시도하는 형태로 분리.

바뀐/새로 생긴 파일: `common/settings.py`, `common/adapters.py`, `common/contracts.py`,
`common/events.py`(신규), `common/database.py`(단일 커밋 지점 `session_scope`),
`common/errors.py`(주석 교체만), `main.py`(CORS 감싸기 + lifespan 로그),
`alembic/versions/0002_event_log.py`(신규) + `alembic/env.py`(import 1줄),
`backend/conftest.py`(신규, `PINGO_ENV=test` 강제), `.env.example`, `README.md:66`,
`backend/CLAUDE.md:36`.

테스트: `common/tests` 42개 수집 — **40 passed, 2 xfailed**(의도된 xfail, 아래 참고).
`pins/tests`·`authz/tests` 중 DB 불필요한 84개 전부 통과, 회귀 없음 확인.

## 꼭 읽어야 할 것 (판단이 들어간 곳)

1. **이 파일 아래 "루트 확인·결정 필요" 항목들.**
2. **`common/settings.py`의 `Settings.__post_init__`** — prod 가드가 전부 여기 모여 있다:
   dev 스텁 잔존 금지, `CORS_ALLOW_ORIGINS=*` 금지, `CORS_ALLOW_ORIGIN_REGEX` 잔존 금지, 빈
   오리진 금지, `SESSION_SECRET` 기본값 금지. 가드 하나가 곧 "prod 배포 전 체크리스트 항목"이다.
3. **`common/adapters.py::select()`의 `is_prod and mode == "dev"` 체크** — 코드 주석에도 적었듯
   **사실상 도달 불가능한 코드**다(모듈이 항상 `settings.<port>_mode`를 넘기면 그 경로는 이미
   `Settings()` 생성 시점에 막힌다). 남겨둔 이유는 "누군가 `select(..., "dev", ...)`처럼 문자열을
   하드코딩하는 실수"를 잡기 위한 것이지 이중 방어선이 아니다 — 이 설계를 받아들일지 확인 바람.
4. **`common/database.py`의 SSE 주의사항** — `get_db`(일반 JSON 응답)는 커밋 실패가 정직하게
   500이 되도록 보장되지만, `StreamingResponse`(SSE)는 이 보장이 적용되지 않는다. `realtime`은
   이 `get_db`에 의존하지 않고 별도 짧은 세션을 쓰기로 이미 조율됨(`realtime/mentor-review-plan.md`
   참고) — root가 이 경계를 인지하고 있어야 나중에 다른 모듈이 SSE에서 `get_db`를 재사용하는
   실수를 막을 수 있다.
5. **`common/events.py`의 `Event.__post_init__`** — `channel`/`recipient_user_id` 일관성을 DB
   `CheckConstraint`보다 먼저(생성 시점에) 잡는다. `EventPublisher`/`NullPublisher`(현재
   `pins/deps.py`에 있음)는 **폐기 대상**이지만 폐기 자체는 `pins`의 계획이 수행한다 — 이 PR은
   대체할 계약(`record_event`)만 제공한다.

## 가볍게 훑거나 생략해도 되는 것

- `common/contracts.py` — 아직 real 구현이 없어 실사용처가 없는 스캐폴딩. `pins`/`authz`가
  real 어댑터를 붙일 때 `assert_signature_matches`를 실제로 호출하기 시작한다.
- `backend/conftest.py` — 3줄, `PINGO_ENV=test` 강제 하나뿐.
- `common/tests/` — 42개 테스트(40 passed, 2 xfailed) 통과로 갈음.

## 루트 확인·결정 필요

**이번 PR이 완료된 게 아니라 다음 단계가 남아있는 것 (조율 필요)**

1. **팀 공지 필요**: `uvicorn main:app` → `uvicorn main:asgi_app`. 이 저장소엔 Dockerfile·CI가
   없어 `README.md`·`backend/CLAUDE.md` 두 곳 외엔 참조가 없지만, 각자 로컬 셸 히스토리는
   자동으로 안 고쳐진다 — root가 채널에 공지해야 한다.
2. **`pins`/`authz`의 `deps.py`가 아직 `select()`로 재배선되지 않았다.** 그래서
   `common/tests/test_adapter_assembly.py`의 `test_every_registered_port_is_accounted_for`와
   `test_adapter_factories_go_through_select` 둘 다 `xfail(strict=False)`로 표시해뒀다 — 지금
   strict로 걸면 이 PR 자체가 자기 테스트에 걸려 실패한다(Antigravity 검수가 잡은 실제
   시퀀싱 버그). **`pins`/`authz` 세션이 각자 재배선을 끝내면 이 두 xfail을 제거하고 strict
   통과를 확인해야 한다** — 이 PR의 책임 범위 밖이라 여기서는 안 건드렸다.
3. **포트 이름 3개가 이미 하드코딩돼 있다**: `pins.PlaceGateway`(#34), `authz.MembershipGateway`
   (#19), `auth.SessionResolver`(#4) — `test_adapter_assembly.py::MISSING_REAL`에 있다. `pins`/
   `authz`가 `select()`를 붙일 때 이 문자열과 정확히 맞춰야 위 2번 테스트가 통과한다. 이름이
   바뀌면 이 파일도 같이 고쳐야 한다는 걸 담당자들에게 알려야 한다.
4. **`alembic upgrade head`가 실제 PostgreSQL에 이번 리비전(`0002_event_log`)까지 아직 안
   돌아갔다.** 이 개발 환경에 Docker가 안 떠 있어(`docker ps` 실패) 마이그레이션 자체를 실제
   DB에 적용해보지 못했다 — 스키마(컬럼·제약·인덱스)는 `common/events.py`의 `EventLog`와
   1:1로 손으로 맞췄지만, `docker-compose up -d` 후 `alembic upgrade head`로 실제 적용 확인이
   필요하다.
5. **`pins/tests/test_pins_api.py`(DB 필요, 30개)를 이 환경에서 못 돌렸다** — Docker 미가동.
   `common`의 `get_db`/`DATABASE_URL` 변경이 이름·기본값을 그대로 유지해 영향 없을 것으로
   설계했지만(플랜의 전제), 실제 DB로 한 번 더 확인 필요.

**이미 내려진 결정 (재확인용, 뒤집을 필요 없으면 그냥 인지만)**

6. **`pydantic-settings`를 넣지 않기로 결정했다** — 표준 `dataclass` + `os.environ` +
   이미 있던 `python-dotenv`로 감. 근거: `requirements.txt`가 핀 고정+lockfile 없음(새 패키지
   추가 시 6명 전원 재설치 필요), 설정 항목이 평탄한 스칼라 ~8개뿐이라 `pydantic-settings`의
   이점(중첩모델·다중소스)이 안 쓰임. 나중에 설정이 복잡해지면 `Settings` 필드명과 `settings`
   싱글턴은 그대로 두고 `from_env()`만 바꾸는 마이그레이션이라 지금 미루는 비용은 낮다고
   판단했다 — root가 다른 판단이면 지금 되돌리는 게 가장 싸다.
7. **App factory(`create_app(settings)`)를 만들지 않기로 결정했다** — `pins/tests/conftest.py:100`
   이 `from main import app` 전역 싱글턴을 이미 쓰고 있어서, 지금 바꾸면 다른 세션 소유 파일을
   강제로 고쳐야 한다. `main.py`는 계속 모듈 레벨 평평한 구조로 두고 `app`(테스트용)과
   `asgi_app`(실제 서빙 대상) 둘 다 노출하는 선에서 멈췄다.
8. **`EVENTS_MODE`라는 어댑터 모드는 없다** — 이벤트 발행은 `select()`로 고르는 포트가 아니라
   `common.events.record_event`를 직접 부르는 평범한 함수 호출로 설계했다(구현이 영원히
   하나뿐인 것에 어댑터 선택 레이어를 씌우지 않는다는 원칙). `.env.example`에도 이 항목을
   일부러 안 넣었다.

**환경 이슈 (common과 무관, 참고용)**

9. 이 개발 환경에 Docker Desktop이 안 떠 있어(`docker ps` → `dockerDesktopLinuxEngine` 파이프
   없음) `docker-compose up -d`를 못 돌렸다. PostGIS가 필요한 모든 검증(마이그레이션 실적용,
   `pins/tests/test_pins_api.py`)은 이 세션에서 완료하지 못했고 위 4·5항으로 남겨뒀다.

---

# 추가 보고 — #101 (PR #94 멘토 리뷰 포인트 2, 2026-09-22)

위 PR #71 작업 이후 `pins`/`authz`/`auth`가 각자 진도를 냈고(포트 이름·`select()` 재배선 등
위 3번 항목은 이미 해소된 상태로 확인됨), 이번엔 별도로 root가 명시 허가한 작업만 진행했다:
**`maps`·`pins`·`shortlist`·`authz` 네 모듈의 `deps.py`가 각자 복붙해둔
`get_db_session()`을 `common/database.py`의 공용 함수 하나로 통일.**

## 문제였던 것

`common.database.get_db`를 감싸는 `get_db_session()`을 `maps`/`pins`/`shortlist`가 각자
파일에 똑같은 몸통(`yield from get_db()`)으로 복붙해뒀고, `authz/deps.py`는 그중 `maps.deps`
걸 가져다 썼다. FastAPI의 요청 스코프 의존성 캐시는 **함수 내용이 아니라 함수 객체 동일성**으로
재사용 여부를 판단한다 — 그래서 예를 들어 `pins` 라우터(자기 `pins.deps.get_db_session`을 씀)와
`authz.guard`의 멤버십 확인(`authz.deps.get_membership_gateway` → `maps.deps.get_db_session`을
씀)이 한 요청 안에서 같이 걸리면 DB 세션이 실제로 2개 열렸다. `common/database.py`의 원칙("요청
하나 = 트랜잭션 하나, 커밋 지점도 하나")이 이 경로에서는 깨져 있었던 것 — 지금까지는 authz 쪽이
조회 전용이라 안 터졌을 뿐, 권한 확인 경로에 쓰기가 하나라도 들어가면 실제 버그가 될 구조였다.

## 한 일

1. `common/database.py`에 `get_db_session()`을 새로 추가(`get_db`와 몸통 동일, 문서화된
   이유는 함수 docstring 참고).
2. `maps/deps.py`·`pins/deps.py`·`shortlist/deps.py`·`authz/deps.py` 네 곳에서 각자 정의를
   지우고 `from common.database import get_db_session`으로 재노출만 하도록 교체
   (`authz/deps.py`는 `maps.deps`가 아니라 `common.database`를 직접 가져오도록 바꿈).
3. 회귀 테스트 추가(`common/tests/test_get_db_session.py`):
   - `test_four_modules_reexport_the_same_function_object` — 네 모듈이 재노출한 이름이
     `common.database.get_db_session`과 정확히 같은 객체인지(`is` 비교) 확인.
   - `test_one_request_opens_exactly_one_session` — 진짜 FastAPI 요청 하나에 `Depends(get_db_session)`을
     두 곳에 걸어, 두 지점이 받는 `Session` 인스턴스가 같은지(`db_a is db_b`) 확인. PostGIS 없이도
     통과(세션을 실제로 쓰지 않으면 커밋도 연결이 필요 없다 — 확인 완료).

## 검증

```
common/tests             44 passed(신규 2개 포함), 회귀 없음
maps/tests                16 passed(DB 필요 27개는 Docker 미가동으로 ERROR — 이 변경과 무관, 아래 참고)
pins/tests(DB 불필요분)    다수 passed, 1개 FAILED — 역시 DB 연결 거부(OperationalError)가 원인,
                          이 변경과 무관(같은 원인의 "ERROR"들과 동일 계열, 이 테스트만 pytest.fail로
                          안 감싸져 있어 FAILED로 표시됐을 뿐)
shortlist/tests, authz/tests, auth/tests  DB 불필요분 전부 passed
```
`maps.deps.get_db_session is pins.deps.get_db_session is shortlist.deps.get_db_session is
authz.deps.get_db_session is common.database.get_db_session` — 전부 `True` 직접 확인.

## 추가 반영 — `auth/deps.py`도 마저 통일함 (root 승인, 같은 날)

10. ~~`auth/deps.py`도 같은 패턴~~ — root 승인 받아 `auth/deps.py`도 자체 정의를 지우고
    `from common.database import get_db_session`로 교체했다. 이제 `maps`/`pins`/`shortlist`/
    `authz`/`auth` 다섯 모듈 전부 같은 함수 객체를 공유한다(`common/tests/test_get_db_session.py::
    test_five_modules_reexport_the_same_function_object`가 다섯 모듈 전부를 `is` 비교로 고정).
    `auth/tests/conftest.py`가 쓰던 `app.dependency_overrides[get_db_session]` 오버라이드는
    재노출된 같은 객체를 키로 쓰므로 그대로 작동함(다른 모듈 override 방식과 동일 원리).
    `common/tests` 44 passed 유지, `auth/tests`의 DB 불필요 14개 회귀 없음 확인.
11. Docker 미가동으로 DB가 실제로 필요한 요청 경로(예: `pins` 라우터 + `authz.guard`가 진짜로
    같이 걸리는 실제 엔드포인트 하나, 또는 `auth.get_current_user` + 다른 모듈 라우터가 같이
    걸리는 경로)에서 "세션 1개"를 종단간으로는 확인하지 못했다. 위
    `test_one_request_opens_exactly_one_session`은 의존성 캐싱 메커니즘 자체를 격리해서
    검증한 것이고, 실제 DB로 한 번 더(`docker-compose up -d` 후 `pytest -q`) 확인하는 걸 권한다.

---

# 추가 보고 — LLM 설정 추가 (2026-09-30, 후속 #116 준비)

## 구현 범위

- `common/settings.py`: `Settings`에 `elice_ml_api_base_url`, `elice_ml_api_key`, `llm_model`(기본
  `gpt-6-luna`), `llm_mode`(dev|real) 추가. 환경변수는 `ELICE_ML_API_BASE_URL`,
  `ELICE_ML_API_KEY`, `LLM_MODEL`, `LLM_MODE`이며 kakao_*와 같은 방식(`_env`)으로 읽는다.
- `_PORTS`에 `"llm"` 추가 → prod에서 `LLM_MODE=dev`면 places/auth와 같은 `ConfigError`로 기동 거부.
  `LLM_MODE` 미지정 시 기본값은 prod=`real`, 그 외=`dev`. `mode_for("llm")` 동작.
- `backend/.env.example`: 키 이름만 추가(실제 키 없음). 빈 값(`KEY=`)은 "설정 안 됨"이 아니라
  "빈 문자열로 설정됨"이라는 점을 `CORS_ALLOW_ORIGIN_REGEX` 사례처럼 주석으로 문서화.
  `LLM_MODEL`은 기본값을 쓰려면 줄을 지우도록 주석 처리.
- 테스트(`common/tests/test_settings.py`): prod+dev 거부(직접 생성·`from_env` 두 경로), 기본값
  (dev/prod), override 읽기.
- 스펙(`docs/*`)은 건드리지 않았다. FE↔BE 구조 변경 없음 → `CHANGELOG-api.md` 기록 대상 아님.

## 루트 확인·결정 필요

1. **`llm_mode` dataclass 기본값을 `"real"`로 뒀다.** places/auth는 필수 필드지만, 기존
   `Settings(...)` 직접 생성 호출부(테스트 등)를 깨지 않으려고 기본값을 줬다. prod 안전 쪽이라
   스텁이 조용히 올라가진 않는다. 필수 필드로 바꾸길 원하면 알려달라.
2. **llm 포트 슬롯은 "준비"만 했다.** `_PORTS`·`mode_for`까지이고 `select("llm.…")` 등록은 하지
   않았다(`backend/llm`이 아직 없음). #116에서 등록할 때 `test_adapter_assembly.py`의
   `MISSING_REAL`에 `"llm.…": "#116"`을 같이 넣어야 테스트가 통과한다.
3. **빈 `ELICE_ML_API_KEY`는 prod에서도 막지 않는다.** kakao_*와 같은 정책(실제 호출 시점에
   실패). prod에서 real인데 키가 비면 기동 거부하길 원하면 결정 필요 — #116에서 같이 정해도 된다.
4. **backend 전체 pytest가 실패 0이 아니다(이 변경과 무관).** 실행마다 21~29건 실패·오류가
   나온다(auth/maps/pins/recommend/shortlist). 이 변경을 임시로 되돌려도 21건 실패해서 원인이
   아님을 확인했다. 건수가 매번 달라 공유 DB 상태 영향일 가능성이 있으나 원인은 확인 못 했다.
   `common` 테스트는 61개 전부 통과. 루트에서 확인 필요.

## 절차 미이행 (보고)

- 작업 폴더가 git 저장소가 아니어서 `develop` pull, 브랜치 생성, develop merge, PR을 하지
  못했다. 변경 파일은 `common/settings.py`, `common/tests/test_settings.py`,
  `backend/.env.example` 3개뿐이다.
- 이 작업의 이슈 번호를 전달받지 못해(#116은 후속) 디스코드 "착수합니다"와 이슈 본문의
  "실제 소요" 기입을 하지 못했다.
- 후속 #116(backend/llm)은 엘리스 ML API 키를 받은 뒤 시작한다 — 지금은 시작하지 않았다.
