# API 계약 워크플로 — FE 병목 제거

목표: 프론트 담당자가 **백엔드 구현 완료를 기다리지 않고** `docs/api-spec.yaml`만으로 전 화면을 개발한다.

**구현 완료 (이슈 #38, 2026-09-02):** 아래 워크플로는 `contracts/` 패키지로 실제로 존재한다. 사용법은 `contracts/README.md` 참고 — 이 문서는 그 설계 배경만 남긴다.

## 1. 타입 생성

```bash
cd contracts && npm run gen:types   # docs/api-spec.yaml → contracts/src/types/api.d.ts
```
스펙이 바뀔 때마다 재실행. CI에 넣어 생성 결과가 커밋된 파일과 다르면 실패시킨다(스펙-코드 드리프트 방지) — #37(CI 이슈)에서 연동.

## 2. 목 서버

`contracts/mocks/`에 `msw`(Mock Service Worker) 핸들러가 `docs/api-spec.yaml`의 24개 경로 전부를 커버한다. 정적 픽스처가 아니라 **상태를 가진 인메모리 스토어**라 핀 찍기→반응→추천→게시→확정 흐름을 실제로 조작할 수 있다. 시나리오는 5개:

- `empty` — 6절 "핀이 하나도 없음"
- `happy-path`(기본값) — 기획안 6절 핵심 시나리오 그대로(로그인→핀→반응→추천→근거→게시→확정)
- `no-results` / `retry-limit` / `region-conflict` — `docs/errors.md`의 각 코드

프론트는 이 목 서버를 백엔드 대신 두고 개발한다. 실제 API가 준비되면 `worker.start()` 두 줄만 지우면 된다. `contracts/mocks/smoke.test.ts`가 6절 전체 흐름 + 4개 에러 시나리오를 자동 검증한다.

## 3. 검증

```bash
cd contracts
npm run lint:spec    # @redocly/cli lint docs/api-spec.yaml — 스펙 자체의 문법·스타일 검증
npm run typecheck    # tsc --noEmit — 핸들러가 생성된 타입과 어긋나지 않는지
npm test             # vitest — smoke.test.ts
```
백엔드 구현체는 별도로 계약 테스트(스펙과 실제 응답 스키마 비교)를 CI에 둔다 — `docs/architecture.md` 6절.

## 4. 스펙 변경 프로토콜 (구조 변경 즉시 보고)

1. `docs/api-spec.yaml` 수정 (루트 Claude Code 또는 승인된 변경만)
2. `docs/CHANGELOG-api.md`에 변경 내용·영향받는 엔드포인트·이유 기록
3. 프론트 담당자에게 즉시 통보 (변경 내용 + 마이그레이션 필요 여부)
4. 타입 재생성, 목 핸들러 갱신

**서브 디렉토리 Claude Code는 이 스펙을 읽기만 한다.** 구현 중 스펙이 부족하거나 잘못됐다고 판단되면 스펙을 직접 고치지 말고 루트에 보고한다 — `CLAUDE.md` 역할 분리 원칙.

## 5. 실서버 연동 점검 — FE↔BE 첫 연결 절차 (2026-10-01)

> **개발을 모르는 사람이 따라 하는 시연 절차는 `docs/demo-guide.md`다.** 이 절은 개발자용 점검표다.

프론트는 지금까지 목 서버(msw)로만 돌았다. 아래 순서로 **실제 백엔드에 붙여** 화면 흐름을 끝까지 돌려 보고, 어긋나는 것은 이슈로 남긴다.
범위는 "실제 API를 연결해 시연하는 v1"이다 — 배포·영구 수집은 포함하지 않는다.

### 5-1. 준비 (한 번)

**백엔드** (`backend/`)
```bash
docker-compose up -d                  # PostgreSQL+PostGIS, Redis
cp .env.example .env                  # 없으면. 값은 커밋하지 않는다
python -m alembic upgrade head        # 마이그레이션 체인이 head 하나여야 한다
# 자체 장소 DB 적재(한 번, 약 4분) — 파일은 저장소 밖에 둔다(.gitignore). 안 하면 검색·핀·추천이 모두 빈다
python -m places.load restaurants --file <restaurant_seoul_curated.csv> --labels <restaurant_seoul_curated_labels.json> --dry-run   # 리포트 확인 후 --dry-run을 뺀다
python -m places.load cafes --file <cafe_seoul_curated.csv> --labels <cafe_seoul_curated_labels.json|.csv> --dry-run          # 카페(분류 '카페'). 좌표 없는 행·모르는 업태는 건너뛰고 건수를 보고한다
python -m uvicorn main:asgi_app --port 8000
```
`backend/.env`에 채울 값 (**localhost로 통일** — `127.0.0.1`과 섞으면 쿠키가 안 붙는다):

| 값 | 설정 | 비고 |
|---|---|---|
| `PINGO_ENV` | `dev` | **꼭 적는다(#126).** 안 적으면 prod로 떠서 prod 가드가 서버 기동을 막는다(`ConfigError`). `AUTH_MODE`는 없어졌다 — 쿠키 값을 믿는 개발용 인증이 사라졌고 로그인은 항상 실제 카카오다 |
| `KAKAO_CLIENT_ID` | 카카오 **REST API 키** | JavaScript 키·Admin 키 아님. 로그인용이자 places가 `KAKAO_REST_API_KEY` 대신 쓴다 |
| `KAKAO_CLIENT_SECRET` | (콘솔에서 Client Secret을 켰을 때만) | |
| `KAKAO_REDIRECT_URI` | `http://localhost:8000/auth/kakao/callback` | 카카오 콘솔 Redirect URI, FE가 만드는 authorize URL과 **글자까지 같아야** 한다 |
| `FRONTEND_BASE_URL` | `http://localhost:5173` | 초대 링크와 로그인 뒤 이동 주소의 기준 |
| `SESSION_SECRET` | 임의의 긴 문자열 | 기본값(`change-me-before-deploy`)이면 prod에서 기동 거부 |
| `PLACES_MODE` / `PLACES_SOURCES` | 실제 검색을 보려면 `real` / `kakao` | `dev`면 고정 샘플 5곳 |
| `LLM_MODE` + `ELICE_ML_API_*`, `LLM_MODEL` | 실제 추천 사유 구조화를 보려면 `real` | `dev`면 스텁 통과 |

**카카오 개발자 콘솔**: 앱에서 카카오 로그인 활성화 → Redirect URI에 위 콜백 주소 등록 → 플랫폼 Web에 `http://localhost:5173` 등록(지도 SDK) → 필요하면 "카카오맵" 사용 설정 ON(로컬 API가 403이면 먼저 확인).

**프론트** (`frontend/.env.local` — 커밋 금지)
```
VITE_API_BASE_URL=http://localhost:8000
VITE_KAKAO_MAP_KEY=<JavaScript 키>
```
`VITE_API_BASE_URL`을 채우면 목 서버가 꺼진다(`api.ts`). 로그인은 FE가 카카오 URL을 만들지 않고 `${VITE_API_BASE_URL}/auth/kakao/login`으로 이동한다(#128, 그래서 `VITE_KAKAO_REST_KEY`는 필요 없다). `npm run dev`로 `http://localhost:5173`을 연다.

### 5-2. 점검 흐름 (화면이 있는 만큼 위에서부터)

| # | 흐름 | 기대 결과 | 어긋나면 먼저 볼 곳 |
|---|---|---|---|
| 1 | `/`에서 로그인 버튼 → `/auth/kakao/login` → 카카오 → 돌아옴 | 내 지도 목록(`GET /maps`) 화면. 브라우저 쿠키에 `session`(HttpOnly)이 생김 | 카카오 `KOE006`(Redirect URI 불일치), 401 반복(쿠키 미저장), 콜백 401 `invalid_state`(login을 안 거치고 카카오로 직접 갔거나 쿠키 호스트 불일치) |
| 2 | 지도 만들기(제목·기간·지역) | `POST /maps` 201 → 그 지도로 이동, 목록에 나타남 | 422(날짜: 종료일은 시작일과 같거나 이후) |
| 3 | 초대 링크 발급 → **다른 브라우저/시크릿 창**에서 열기 | 비로그인으로 초대 요약(`GET /invites/{token}`) 표시 → 로그인 → 수락 → 같은 지도, 구성원 2명 | 링크 호스트가 `FRONTEND_BASE_URL`인지, 410(만료)/404(없는 토큰) 화면 |
| 4 | 이름 검색으로 핀 찍기 (`GET /places/search`) | 결과에 `pinnable`(자체 DB에 짝이 있는가) — false여도 「그래도 핀 남기기」(source=live, #382, 메모 입력)로 핀을 남길 수 있다. 고르면 `POST /maps/{id}/pins`(source=search) 201, 핀 이름·좌표는 **자체 DB 장소의 것**. 0개면 "결과 없음" | 422 `PLACE_NOT_SUPPORTED`(자체 DB에 없음 — 서울 음식점 11,843곳·카페 533곳만 있다), 429(빨리 침), 503(검색 불가) |
| 5 | 같은 핀이 다른 창에 **실시간으로** 나타남 | SSE `pin.created`. 같은 장소를 또 찍으면 409 `PIN_DUPLICATE`. 지도 길게 눌러 찍기·링크로 찍기는 없다(v1에서 뺌, 보내면 422) | 다른 창에 안 뜨면 `GET /maps/{id}/events` 연결(401/CORS) |
| 6 | 핀 상세: ♥/🚫 남기기, 의견 목록, 내 반응 취소 | 🚫는 사유 없으면 422 `EVIDENCE_REQUIRED`. (숙소는 v1에서 핀 자체를 만들 수 없다) | `my_reaction`, 반응 요약이 바로 갱신되는지 |
| 7 | 추천 받기(음식점) → 근거 확인 → 실행 | 준비 미달이면 409 `NOT_READY`. 후보는 **요청자에게만** 점선 핀. 후보 카드에 이유·체크·구성원 충족·출처 | 다른 구성원 화면에 후보가 보이면 가드레일 1 위반 — 즉시 이슈 |
| 8 | 반경 넓히기 ×4, 다시 추천 | 15→20→25→30분, 네 번째는 409 `WIDEN_LIMIT`. 재시도 5회 초과는 429 `RETRY_LIMIT` | |
| 9 | 「지도에 올리기」 | 모든 구성원에게 핀이 나타나고 이유·체크가 **게시 뒤에도 유지** | |
| 10 | 확정 리스트 추가/제외, 순서 바꾸기, 동선 | 순서 변경은 동선을 바꾸지 않음. 동선은 「동선 짜주기」로만 | |
| 11 | 이름 변경, 로그아웃 → 다른 탭 요청 | 로그아웃 이후 이전 쿠키는 401(모든 기기 세션 종료) | |
| 12 | 탈퇴 | 내 반응·사유 삭제, 핀은 남고 작성자는 "탈퇴한 구성원" | |

### 5-3. 자주 나오는 문제

| 증상 | 원인 | 조치 |
|---|---|---|
| 요청마다 401, 로그인 루프 | 쿠키가 안 붙는다 — 호스트 혼용(`127.0.0.1`↔`localhost`) 또는 `credentials: 'include'` 누락 | 주소를 `localhost`로 통일 |
| 브라우저 콘솔에 CORS 오류 | 오리진이 허용 목록에 없다 | dev는 localhost 정규식이 기본 허용. 다른 오리진이면 `CORS_ALLOW_ORIGINS`에 명시(와일드카드 불가) |
| 카카오 `KOE006` | Redirect URI가 콘솔·BE·FE 셋 중 하나와 다르다 | 세 곳을 글자까지 일치 |
| 서버가 안 뜨고 `ConfigError` | `PINGO_ENV`를 안 적으면 prod로 뜬다(#126) — prod 가드(기본 시크릿·와일드카드 CORS 등) | `backend/.env`에 `PINGO_ENV=dev`, 또는 값 채우기 |
| `relation "..." does not exist` | 마이그레이션 누락 | `python -m alembic upgrade head` |
| `503 PLACES_UNAVAILABLE` | `PLACES_MODE=real`인데 카카오 키 없음/장애/403 | 키·"카카오맵" 사용 설정 확인, 또는 `dev`로 |
| 추천이 항상 `NO_RESULTS` | dev 장소 라벨이 전부 unknown인 상태에서 안전 조건(갑각류 등)이 켜졌다 — **정상 동작**(모르면 제거) | 실제 라벨링(데이터 담당)이 붙기 전까지 시연에서는 안전 조건을 켜지 않은 사유로 |
| 옛 테이블 컬럼이 없다는 오류 | 로컬 테스트 DB가 오래됨 | 테스트 DB만 삭제 후 재생성 |
| 핀에 카카오 좌표·이름이 저장된다 | #53 결정(2026-10-01) 전의 임시 동작 — 자체 장소 DB(#189)와 핀 찍기 규칙(#191)이 들어오기 전까지 로컬 개발 DB에만 쌓인다 | **배포 전에 그 로컬 DB를 지운다**. 시연 DB를 그대로 배포하지 않는다 |

### 5-3-1. 알려진 한계 (v1 시연 전에 알아 둘 것)

| 한계 | 증상 | 시연에서는 | 기록 |
|---|---|---|---|
| 검색 원이 카테고리 핀의 **중심점 하나**(핀마다 원이 아니다) | 서로 멀리 떨어진 핀(예: 성수와 홍대)만 있으면 두 곳 사이 빈 땅이 중심이 되어 추천이 비어 보인다(404 `NO_RESULTS`). 반경을 넓혀도 같다 | **핀을 한 동네에 모아 찍는다** | #226 — v1에서 수정하지 않기로 결정(2026-10-02), 재현 테스트가 xfail로 남아 있다 |
| 자체 장소 DB가 서울 음식점 11,843곳·카페 533곳뿐 | 관광지는 후보가 없다. DB에 없는 가게는 자체 DB 핀은 안 되고(`PLACE_NOT_SUPPORTED`) 실시간 핀(`source: live`, #382)으로 남긴다 — 장소 정보·AI 후보·동선은 없다. **카카오 검색 결과 중 자체 DB 핀이 되는 것은 일부(약 15%)다** | 음식점 시나리오만, 서울. 핀이 되는 가게를 미리 정해 둔다(`docs/demo-guide.md` 장면 3) | #189·#207·#266 |
| `price_bucket`이 항상 통과 | 가격 조건("비싸요")은 체크로 보일 뿐 걸러내지 않는다 | 가격 사유는 쓰지 않는다 | #112 |
| 갑각류 사유는 음식점을 전부 제외 | 라벨에 거짓이 없다("거짓은 만들지 않는다") — 「갑각류 알러지가 있어요」 칩을 쓰면 후보 0곳 | 갑각류 칩은 시연에서 쓰지 않는다. **매운맛 칩**(`spicy_focused` 거짓 확인 4,865곳)을 쓴다 | docs/constraints.md |

### 5-4. 결과 기록

- 어긋난 항목은 이슈로 남긴다. 제목 접두어: `[연동]`, 라벨 `fe`/`be` 중 원인 쪽 + `bug`. 본문에 **흐름 번호(5-2), 요청 URL, 응답 코드·본문, 기대 결과**를 적는다.
- 응답 모양이 스펙과 다르면 FE가 아니라 스펙 기준이다 → BE 이슈. 스펙 자체가 틀렸다면 루트에 보고(스펙 변경 프로토콜 4절).
- 이 점검은 `backend/integration/`의 응답 계약 테스트가 못 보는 것(브라우저 쿠키·CORS·리다이렉트·SSE 실시간 반영)을 본다.
