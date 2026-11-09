# 기술 스택

작성 기준: `develop`(2026-11-03, 숫자와 상태는 2026-11-10에 다시 맞춤). 이 문서는 **지도**다 — 버전과 동작의 정본은 각 절의 근거 파일이고, 어긋나면 파일이 맞다. 숫자(경로 수, 버전)는 이 시점에 읽은 값이라 시간이 지나면 달라질 수 있다. 확인하지 못한 것은 「확인 못 함」으로 적는다. 제품 스펙은 `최종기획안.md`, 기술 계약은 `docs/`가 정본이다(루트 `CLAUDE.md`의 문서 지도).

## 1. 한눈에 보기

```
브라우저(React SPA · 카카오맵 JS SDK)
   │  HTTPS            ┌─ /api/*  → api 컨테이너(단일 FastAPI 앱, 모듈 18개)
   ▼                   │                │            │
 Caddy(edge) ──────────┤                │ SQL        │ HTTPS(서버에서만)
 80/443, Let's Encrypt └─ 그 밖 → web 컨테이너(정적 파일)   ▼            ▼
                                       PostgreSQL 17 + PostGIS 3.5   카카오(OAuth·로컬 검색) · OpenAI
                                       (운영·스테이징 RDS 한 대, DB 둘)
```

| 핵심 선택 | 한 줄 이유 | 상세 |
|---|---|---|
| **단일 FastAPI 앱, 모듈형** | 서버 1대·작은 팀. 모듈 경계는 import 규칙 검사로 지킨다 | 2절 |
| **실시간은 SSE + `event_log` 폴링** | 상태 변경과 같은 트랜잭션에 이벤트를 남겨 유실을 막는다 | 4절 |
| **계약 우선(OpenAPI 3.1)** | `docs/api-spec.yaml`이 정본, FE 타입·목 서버가 여기서 파생된다 | 6절 |
| **모델 호출을 최소화** | 요청 중 모델 호출은 ② 사유 구조화 하나, 필터·순위·동선은 코드가 한다 | 7절 |
| **카카오 응답은 저장하지 않는다** | 약관(#53). 장소 ID와 `place_url`만 저장할 수 있다 | 7절 |

## 2. 백엔드

근거: `backend/requirements.txt`(운영, 전부 `==` 고정), `backend/requirements-dev.txt`(테스트·개발 도구, #1439), `backend/.python-version`, `backend/pyproject.toml`, `backend/main.py`, `backend/Dockerfile`.

| 구분 | 패키지 | 버전 | 쓰이는 곳 |
|---|---|---|---|
| 언어 | Python | 3.12 | `.python-version`이 정본, Dockerfile·CI가 같은 값을 쓰고 `integration/test_env_parity.py`가 확인 |
| 프레임워크 | fastapi | 0.115.0 | `main.py` |
| 서버 | uvicorn[standard] | 0.30.6 | Dockerfile CMD |
| 검증 | pydantic | 2.9.2 | 모듈별 `schemas.py`, LLM 구조화 출력 |
| ORM | sqlalchemy | 2.0.35 | `common/database.py` |
| 마이그레이션 | alembic | 1.13.3 | `backend/alembic/versions/`(현재 head `0070_course_run_pin_ids_drop`, 0026·0027은 번호 없음) |
| DB 드라이버 | psycopg2-binary | 2.9.9 | DB URL `postgresql://` |
| 공간 | geoalchemy2 / pyproj | 0.15.2 / 3.6.1 | 좌표·거리, 공공데이터 좌표 변환(`places/ingest.py`) |
| HTTP 클라이언트 | httpx | 0.27.2 | 카카오 OAuth, 장소 소스, 링크 해석 |
| LLM SDK | openai | 3.22.1(파일 표기) | `llm/client.py` — 실제 설치 버전은 확인 못 함 |
| 설정 | python-dotenv, pyyaml | 1.2.2, 6.0.2 | `common/settings.py`, `agent/core.py` |
| 테스트 | pytest, pytest-asyncio, jsonschema | 9.0.3, 1.3.0, 4.23.0 | 아래 10절 |
| 구조 검사 | import-linter | 2.15 | `backend/pyproject.toml`의 계약, CI `lint-imports` |

린터·포매터(ruff, black, mypy) 설정은 없다.

### 구조
- **하나의 FastAPI 앱**(`main:asgi_app`)에 라우터 16개를 붙인다. 마이크로서비스가 아니다. CORS 미들웨어가 앱 바깥을 감싼다. `auth_qa_router`는 staging에서 `QA_LOGIN_SECRET`이 있을 때만 붙는다.
- **모듈 18개**(`pyproject.toml`의 `root_packages`): 수평 레이어 `common`, `auth`, `authz`와 기능 모듈 `maps`, `pins`, `places`, `seeding`, `recommend`, `llm`, `shortlist`, `realtime`, `notifications`, `feedback`, `maintenance`, `ads`, `credits`, `reviews`, `agent`.
- **모듈 간 규칙**: 다른 모듈은 `api.py`·`schemas.py`만 import한다(`integration/test_import_rules.py`와 import-linter가 검사). 다른 모듈 테이블을 가리키는 열은 문자열이고 DB FK를 걸지 않는다(`docs/architecture.md` 1절). 하위 층(common, auth, authz)은 기능 모듈을 import하지 않는다 — 알려진 예외는 `pyproject.toml`에 한 줄씩 등록돼 있다.
- **실행**: uvicorn 워커 1개, `--proxy-headers`, 비루트 사용자, `/health`로 HEALTHCHECK. `/health`는 SSE 폴러(realtime dispatcher)가 죽었으면 503이다(#1200). lifespan이 폴러를 띄우고 끊긴 AI 코스 run을 정리하고 `agent_loop`를 시작한다.
- **DB 풀 기본값**: pool 5 + overflow 10, `pool_pre_ping` 켬, recycle 없음 — 전부 설정값(`common/settings.py`).

### 설정과 보안
- **환경**: `PINGO_ENV`는 dev·test·staging·prod, 값이 없으면 prod. **모드 스위치** `PLACES_MODE`·`LLM_MODE`(dev 스텁 / real, staging·prod 기본 real), `PLACES_SOURCES`, `AGENT_LOOP_IN_PROCESS`, `CREDIT_AD_PROVIDER`, `COOKIE_SECURE`.
- **기동 가드**(`common/settings.py` `__post_init__`): staging·prod에서 스텁 모드, `CORS=*`, 빈 CORS, 기본 `SESSION_SECRET`, 빈 `FRONTEND_BASE_URL`, real 모드인데 외부 키가 비어 있는 경우, prod의 `QA_LOGIN_SECRET`·fake 광고를 막는다. 추가 가드는 #1210.
- **세션**: 무상태 HMAC-SHA256 서명 토큰, TTL 30일, 로그아웃·탈퇴는 `users.sessions_valid_after`로 이전 토큰을 무효화한다. 쿠키는 `session`, `kakao_oauth_state`, `google_oauth_state`(#1514), `pending_account` 넷이고 모두 httpOnly·`SameSite=lax`(`auth/router.py`).
- **로그 보호**: `common/logguard.py`가 접근 로그의 쿼리 문자열과 초대 토큰 경로를 가리고 SQL 매개변수가 든 예외 출력을 걸러낸다(#1201). httpx·httpcore 로그는 WARNING부터.

## 3. 데이터

| 항목 | 내용 | 근거 |
|---|---|---|
| DB | PostgreSQL **17** + PostGIS **3.5**. 로컬 `postgis/postgis:17-3.5`, CI 서비스 동일, 운영·스테이징은 RDS(17.11, PostGIS 3.5.6) | `backend/docker-compose.yml`, `.github/workflows/backend-test.yml`, `deploy_rules.md` |
| 확장 | `postgis`(`0001_pins.py`), `pg_trgm`(`0042_places_trgm_search.py`). RDS에서는 앱 계정이 확장을 만들 수 없어 `deploy/rds/setup.sql`을 마스터로 먼저 돌린다 | alembic, `deploy/rds/` |
| 마이그레이션 | Alembic 단일 head. **이전 코드가 새 스키마에서 돌아야 한다**(expand → contract 분리). 배포는 마이그레이션을 먼저 올린 뒤 앱을 바꾼다 | `deploy_rules.md`, `deploy/deploy.sh` |
| 스키마 | 테이블 단위 설명 | `docs/data-model.md` |
| 장소 데이터 3층 | ① 구조화 필드(인허가·TourAPI 공공데이터, `places`) ② 반구조화 값(차원 압축 라벨, `place_facts`) ③ 판단 라벨(데이터 담당이 만든 파일을 적재 — v1은 요청 중 모델로 만들지 않는다) | `docs/architecture.md` 2절 |
| 세션·멱등키·재전송 | Redis가 아니라 **PostgreSQL**(무상태 쿠키, 멱등키 테이블, `event_log`) | `최종기획안.md`, `docs/events.md` |

## 4. 실시간(SSE)

근거: `docs/events.md`, `backend/realtime/`, `frontend/src/features/map/realtime.ts`.

- **기록**: 모든 상태 변경이 `common.events.record_event`로 **같은 트랜잭션**에 `event_log`를 남긴다.
- **전달**: realtime dispatcher가 **0.5초마다 폴링**해 구독자에게 SSE로 보낸다. at-least-once, seq에 구멍이 생기면 최대 2초 기다린다. 채널은 지도 공개 이벤트(`/maps/{mapId}/events`)와 개인 이벤트(`/maps/{mapId}/events/me`) 두 개. ping은 20초마다, 재전송 보존 창은 24시간.
- **프록시**: Caddy가 `flush_interval -1`로 SSE를 바로 흘려보낸다(`deploy/Caddyfile`).
- **화면**: `EventSource`는 `realtime.ts` 한 곳. 이벤트는 TanStack Query 캐시에 반영하거나 해당 쿼리를 무효화한다. **60초 무수신 재연결**(#832)이 들어갔다(`realtime.ts`의 `STALE_MS`). 개인 채널은 스펙과 목에는 있지만 FE가 구독하는 곳은 확인하지 못했다.
- **한계**: 폴러가 프로세스 안 백그라운드 태스크라 API 컨테이너 1개를 전제한다. 구독 큐 상한·스레드 경계는 #1211.

## 5. 프론트엔드

근거: `frontend/package.json`·`package-lock.json`(설치 버전), `frontend/CLAUDE.md`, `frontend/DESIGN.md`, `frontend/PRODUCT.md`, `frontend/vite.config.ts`.

| 구분 | 패키지 | 선언 → 설치 |
|---|---|---|
| UI | react / react-dom | ^19.2.8 → 19.3.0 |
| 언어·빌드 | typescript / vite / @vitejs/plugin-react | ~6.0.2 → 6.0.3 / ^8.3.0 → 8.3.0 / 6.1.1 |
| 스타일 | tailwindcss, @tailwindcss/vite | ^4.3.3 → 4.3.3 (Vite 플러그인, `tailwind.config` 없음) |
| 서버 상태 | @tanstack/react-query | ^5.103.1 → 5.103.1 |
| UI 상태 | zustand | ^5.0.15 → 5.0.15 |
| 라우팅 | react-router | ^8.4.0 → 8.4.0 |
| 부품 | radix-ui, shadcn(style radix-nova), lucide-react, tw-animate-css | ^1.6.7, ^4.21.0, ^1.46.0, ^1.4.0 |
| 글꼴 | pretendard | 1.3.9(고정) |
| 테스트 | vitest, jsdom, msw, @testing-library/react·jest-dom·user-event | ^5.0.5, ^30.1.3, ^2.15.0, 16.3.3·7.0.1·14.6.8 |
| 린트 | oxlint(react·typescript·oxc 플러그인) | ^1.81.0 → 1.83.0 |

- **구조**: 피처 단위 `src/features/*`, 공통 부품 `src/ui/*`, 클래스 부품(`btn-*`, `chip`, `tag`, `field`)은 `src/index.css`. 서버 상태는 TanStack Query, 순간 UI 상태는 Zustand로 나눈다.
- **디자인 규칙**: 색 값은 `src/styles/tokens.css`만(정본, 이유는 `docs/design/colors.md`), 버튼 `btn-lg/md/sm`, 글자 크기 8단계, 아이콘은 lucide만. 접근성은 WCAG 2.2 AA·터치 44×44px. 모바일 우선(iPhone 16 프레임 393×852), PWA는 아니다.
- **지도**: 카카오맵 JS SDK를 명령형으로 쓴다(공식 React 래퍼 없음, `features/map/kakaoMap.ts`). 타입 선언은 직접 쓴 `kakao.d.ts`. 키 환경변수는 `VITE_KAKAO_MAP_KEY`.
- **API 호출**: `src/api.ts` 한 곳. `fetch` + `credentials: 'include'`, 에러 봉투 `{code, message, detail?}`를 `ApiError`로 감싸 **status가 아니라 `code`로 분기**한다. `VITE_API_BASE_URL`이 비면 개발 모드에서 msw 목 서버를 쓴다.
- **빌드·서빙**: Docker 멀티스테이지(`node:22-alpine`에서 빌드 → `caddy:2.8-alpine`이 정적 파일 서빙), SPA fallback, `/assets`만 immutable 캐시, 빌드 시 `VITE_API_BASE_URL=/api`.
- **Node**: 루트 `.nvmrc`(22)와 `frontend`·`contracts`의 `engines.node >=22.19.0`(jsdom의 undici 요구, `frontend/package-lock.json`), CI는 `node-version: 22`, Dockerfile은 `node:22-alpine`. npm(`package-lock.json` v3)이고 워크스페이스는 쓰지 않는다 — `contracts`는 경로 alias로 참조한다.

## 6. API 계약

근거: `docs/api-spec.yaml`, `docs/openapi-workflow.md`, `contracts/`.

- **OpenAPI 3.1**, 경로 78개·오퍼레이션 96개·스키마 148개·태그 14개(auth, maps, pins, places, recommend, shortlist, realtime, notifications, feedback, ads, course, credits, reviews, agent). 전역 보안은 쿠키 `session`.
- **타입 생성**: `contracts`의 `npm run gen:types`(openapi-typescript 7.13)가 `contracts/src/types/api.d.ts`를 만들고 **커밋한다**. CI가 `gen:types` 뒤 `git diff --exit-code`로 어긋남을 잡는다.
- **목 서버**: `contracts/mocks/`의 msw 핸들러가 상태를 가진 인메모리 스토어로 응답한다. 시나리오 11개(`empty`, `happy-path`, `no-results`, `region-conflict`, `guest`, `withdrawn-relogin`, `credits-empty`, `credits-full`, `agent-declared`, `agent-linked`, `agent-schedule`). SSE도 흉내 낸다.
- **lint**: `@redocly/cli`(`npm run lint:spec`). **CI에서는 돌지 않는다.**
- **변경 절차**: `docs/api-spec.yaml` → `docs/CHANGELOG-api.md` → errors/events/permissions 문서 → `contracts`(타입·목·smoke 테스트) → 구현. 구현 PR이 CI 가드(`KNOWN_MISSING`, `KNOWN_UNCOVERED`, `KNOWN_DRIFT`)의 항목을 지운다.

## 7. 외부 서비스와 데이터 정책

| 서비스 | 용도 | 비고 |
|---|---|---|
| 카카오·구글 OAuth | 로그인(구글은 #1514, 같은 방식) | FE는 인가 URL을 만들지 않고 `/auth/kakao/login`으로 이동, 서버가 state 쿠키를 심고 카카오로 보낸다(`auth/core.py`, `auth/service.py`) |
| 카카오 로컬 검색 | 장소 검색 | 서버가 `dapi.kakao.com`을 부른다. **응답 저장·캐시·LLM 전송 금지**, 장소 ID와 `place_url`만 저장 가능(`docs/architecture.md` 2절, #53). `integration/test_kakao_no_store_e2e.py`, `test_places_no_kakao_leak.py`가 검사 |
| 카카오맵 SDK | 지도 표시, 실시간 핀 위치 재조회 | FE가 직접. 결과는 메모리에만 둔다 |
| 네이버 | 장소 소스 코드는 있으나 기본 꺼짐(`PLACES_SOURCES=kakao`) | `naver.me` 단축 링크의 **리다이렉트 한 번**만 따라간다(#1048) |
| 공공데이터 | 인허가 음식점·카페, TourAPI 관광지 적재 | `places/ingest.py`, `load` 스크립트 |
| **LLM** | 아래 | `backend/llm/`, `최종기획안.md` 13절 |
| 광고 | 추천 탭은 자체 등록 광고(CSV 스크립트, `docs/ads.md`). 크레딧 광고는 제공자 스위치 `CREDIT_AD_PROVIDER`(`""`/fake/adsense/gpt) | adsense·gpt는 아직 구현 안 됨, 운영에서 fake면 서버가 뜨지 않는다. 페이즈 1 운영은 둘 다 쓰지 않는다(추천 탭 광고는 등록하지 않고 크레딧 광고는 비움, 기획안 16절) |

### LLM
- **제공자**: OpenAI를 직접 호출한다(2026-11-02, #1120). 모델 `gpt-6-luna`(`LLM_MODEL`로 바꿀 수 있다). **환경변수 이름은 엘리스 시절 그대로** `ELICE_ML_API_BASE_URL`·`ELICE_ML_API_KEY`다. 코드의 기본 주소는 빈 문자열이고(비면 호출이 실패), `https://api.openai.com/v1`은 `deploy/env/*.env.example`에 들어 있다. **운영 서버가 실제로 전환됐는지는 서버 env를 확인해야 한다**(`deploy_rules.md`는 운영이 아직 옛 설정이라고 적는다).
- **호출 방식**: `chat.completions.parse` + Pydantic 구조화 출력, 타임아웃 15초, 재시도 0. 단가·일일 예산(3,000원)은 `common/settings.py`. 호출 1건마다 `llm_calls`에 한 행(종류와 결과 `ok`·`refusal`·`empty`·`timeout`·`invalid_schema`·`call_failed`, #870)을 남긴다.
- **호출 지점(정확히)**: **요청 중 호출은 v1에서 ② 사유 구조화(`plan_evidence`) 하나**다. ③-a-1 장소 라벨링(`label_place`)은 **v1 스텁이라 모델을 부르지 않는다**(원자료에 값이 있을 때만 known). 호출 종류는 `llm/models.py`의 `CALLS` 7개 — `plan_evidence`, `agent_diagnose`, `agent_status`, `agent_web_check`, `course_goals`, `course_direct`, `course_turn`(뒤의 여섯은 v2 에이전트·AI 코스, `course_turn`은 평가·시연 전용).
- **모델이 하지 않는 일**: 실격 필터, 선호 순위(점수), 반경·동선 계산, 카카오 대화 해석은 전부 코드가 한다(`CLAUDE.md`의 「모델 호출」 절).

## 8. 배포·인프라

근거: `deploy_rules.md`(결정과 이유), `deploy/`, `.github/workflows/`.

- **구성**: 부트캠프 제공 AWS EC2 1대(t3.medium, 2 vCPU·4GB, Ubuntu 24.04, 서울, **2026-11-20까지**), SSM 접속(22번 포트 닫힘), Elastic IP. 운영과 스테이징을 **같은 서버**에서 컨테이너·DB 이름·비밀값으로 나눈다. 주소는 DuckDNS(`ktc-pingopingo.duckdns.org`, `staging.…`), 인증서는 Caddy가 Let's Encrypt로 받는다.
- **DB**: RDS 한 대에 `pingo_prod`·`pingo_staging`, 환경마다 앱 계정, `sslmode=require`(2026-10-30 이전).
- **Compose**(`deploy/compose.yml`): `edge`(caddy:2.8-alpine, 80/443), `api-prod`·`web-prod`·`api-staging`·`web-staging`. `/api/*`는 `/api`를 떼고 API로, 나머지는 정적 화면으로. 로그는 json-file 10m×3.
- **이미지**: GitHub Actions가 API·화면 이미지를 만들어 팀 계정 ECR(`pingo-api`, `pingo-web`, 최근 40개)에 올린다. 태그는 `sha-7자리`, 브랜치, `v*`.
- **배포 순서**(`deploy/deploy.sh <환경> <태그>`): 이미지 받기 → 운영이면 `backup.sh` → `alembic upgrade head` → 컨테이너 교체 → 90초 건강 확인 → 실패하면 이전 태그로 자동 롤백(스키마는 되돌리지 않는다). 같은 환경의 동시 배포는 flock으로 막는다. 롤백은 이전 `v` 태그로 `deploy` 워크플로를 다시 돌린다.
- **백업**: `pg_dump -Fc`, 14일 보관, 서버 디스크(별도 환경 복원 검증은 아직 없다 — #1203, #1204).
- **cron**(`deploy/crontab`): `maintenance.run`(운영 03:30, 스테이징 03:40), 운영 백업 04:00, `agent.tick` 5분마다(양쪽). DuckDNS 갱신은 꺼져 있다.
- **비밀**: 서버의 `deploy/env/*.env`(권한 600). 값은 저장소에 없고 `*.env.example`에 이름만 있다.
- **개선 예정**: 배포 후 검증 확장 #1214, 운영 설정 가드 #1210.

## 9. CI/CD와 품질 게이트

| 워크플로 | 하는 일 |
|---|---|
| `backend-test` | postgis 17-3.5 서비스 위에서 `lint-imports` → `alembic upgrade head` → `pytest -q`. `develop` 보호 규칙의 필수 검사는 `contracts`·`pytest`·`frontend`(GitHub 설정, 2026-11-03 확인) |
| `frontend-test` | Node 22: oxlint → vitest → build(`tsc -b` 포함) |
| `e2e` | 핵심 흐름 브라우저 E2E(Playwright, #1281). postgis 서비스 위에 실제 백엔드(모델 스텁, 시드한 정예 장소)와 화면 빌드를 띄워 방장·구성원 두 브라우저로 돈다. 아직 필수 검사가 아니다 |
| `contracts-test` | `gen:types` → 생성 타입 diff 검사 → typecheck → test |
| `pr-size` | PR 범위 코멘트(병합을 막지 않는다) |
| `images` | develop·main·`v*` 태그에서 OIDC 역할로 ECR에 이미지 푸시, develop이면 스테이징 배포를 부른다 |
| `deploy` | 수동 또는 호출로 SSM으로 서버의 `sync.sh`·`deploy.sh` 실행. 운영은 `v` 태그만 |
| `staging-check` | 매일 06:00(KST) 서버 안에서 QA 하네스 실행 |
| `uptime` | 10분마다 서버 밖에서 운영·스테이징의 `/`와 `/api/health` 확인. 실패하면 경보 이슈를 열고 회복하면 닫는다(#1280) |
| `llm-cost`, `move-to-rds` | 수동 실행 |
| `assign-mentor`, `convention-check`, `notify-discord` | main 대상 PR 보조(안내용, 차단 안 함) |

- **병합**: 저장소 설정이 **merge commit만 허용**한다(스쿼시·리베이스 병합은 꺼져 있음, GitHub 설정, 2026-11-03 확인). 기준·PR 대상은 `develop`, `main`은 릴리스용. 브랜치 `feat/<주제>-<이슈#>`, 커밋 `type(scope): 요약 (#이슈)`.
- **계약·구조 가드**: `integration/test_spec_route_coverage.py`(`KNOWN_MISSING`), `test_response_contract.py`(`KNOWN_UNCOVERED`), `test_request_constraints_match_spec.py`(`KNOWN_DRIFT`), authz 정책 표 일치, `errors.md` ↔ 에러 카탈로그, import 규칙, 환경 일치(`test_env_parity.py`).

## 10. 테스트·QA

- **백엔드**: pytest, **실제 PostgreSQL**(모킹하지 않는다). 동시에 여러 터미널에서 돌릴 때는 `PINGO_TEST_DB`로 DB를 분리한다. `live` 마커(실제 외부 API)는 기본 실행에서 뺀다(`pytest.ini`). 통합·계약 테스트는 `backend/integration/`에 41개 파일.
- **프론트**: vitest + testing-library + msw(목 서버 시나리오 재사용). 접근성은 자동 검사 도구(axe 등)가 아니라 testing-library로 포커스·알림 영역을 직접 검증한다(`src/a11y.test.tsx`).
- **E2E**(`e2e/`, #1281): Playwright로 지도 만들기 → 구성원 참여 → 핀 → 🚫 사유 → 추천 받기 → 「지도에 올리기」를 돈다. 구성원 화면은 새로고침하지 않아 실시간(SSE)까지 본다. 로그인은 카카오 대신 `auth.testing.session_cookie`, 모델은 스텁, 장소는 `e2e/seed.py`가 넣은 정예, 카카오 지도 키 없이 목록과 시트로 돈다. 실행법은 `qa/README.md`.
- **QA 하네스**(`qa/`): 케이스 대장 `qa/cases.yaml`, 실행기는 `qa/harness/`의 `run_api_cases.py`(실제 HTTP, `--base-url`, `POST /auth/qa-login`), `run_reco.py`, `run_complex.py`, `run_llm_cost.py`. 격리 DB `pingo_eval`, 결과 기록은 `qa/results/`. 스테이징에서 매일 자동 점검(`staging-check`).

## 11. 개발 환경

- **백엔드 로컬**: `cd backend && docker-compose up -d`(PostgreSQL+PostGIS) → `alembic upgrade head` → `uvicorn main:asgi_app --reload`. 설정은 `backend/.env`(견본 `.env.example`, 값 출력·커밋 금지).
- **프론트 로컬**: `contracts`에서 `npm ci`, `frontend`에서 `npm ci` 후 `npm run dev`. `VITE_API_BASE_URL`이 비면 목 서버. `localhost`와 `127.0.0.1`을 섞으면 쿠키가 붙지 않는다.
- **문서 지도**: 루트 `CLAUDE.md`. 모듈별 규칙은 `backend/CLAUDE.md`, `backend/<module>/CLAUDE.md`, `frontend/CLAUDE.md`.

## 12. 알려진 한계 (2026-11-03 기준, 사실만)

| 항목 | 상태 | 추적 |
|---|---|---|
| 개인 SSE 채널 | 스펙·목에는 있고 FE 구독 확인 못 함 | #13 |
| 운영 LLM 제공자 전환 | v0.1.0 배포 때 OpenAI 직접 호출로 맞춤(`deploy_rules.md` 「배포 전에 정할 것」) | #1203 |
| RDS `max_connections`, 운영 마이그레이션 실제 리비전 | 확인 못 함 | #1203, #1204 |
| 백업 복원 검증 | 아직 없음 | #1204 |
| 폴러 큐 상한·스레드 경계 | 상한 없음 | #1211 |
| OpenAPI lint(`lint:spec`) | CI에서 안 돎 | #1204 |
| 배포 후 검증, 운영 설정 가드 | 확장 예정 | #1214, #1210 |
| 2026-11-20 AWS 종료 이후 인프라 | 결정 대기 | #1203 |
