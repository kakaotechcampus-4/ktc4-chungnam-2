# qa/: 출시 전 검증 기록

- `cases.yaml`: 케이스 대장입니다(id, layer, scenario, expect, status). 결과가 나올 때마다 status를 고칩니다.
- `data/`: 합성 테스트 입력(사유 코퍼스 등)입니다. 공공데이터 원본이나 실사용자 데이터는 여기 두지 않습니다.
- `harness/`: 실행기입니다. `run_reco.py`는 실제 모델 추천 품질을, `run_api_cases.py`는 API edge 케이스를 봅니다. 둘 다 backend 폴더에서 격리 DB(`pingo_eval`, pingo_demo 복사본)를 쓰고 키는 출력하지 않습니다.
- `results/<날짜>.md`: 실행 기록(입력, 실제 결과, 판정)입니다. 날짜별로 쌓습니다.

실행 예: `cd backend && PYTHONUTF8=1 DATABASE_URL=postgresql://pingo:pingo@localhost:5432/pingo_eval python ../qa/harness/run_api_cases.py [ID ...]`

`run_api_cases.py`는 실제 HTTP로도 돌릴 수 있습니다(#788). 띄워 둔 서버 주소를 주면 같은 케이스를 그 서버에 보냅니다. 백그라운드 작업, 쿠키, 프록시, 인스턴스마다 따로 세는 상한처럼 배포에서만 생기는 문제를 여기서 봅니다.

- 서버는 `PINGO_ENV=staging`과 `QA_LOGIN_SECRET`으로 띄웁니다(`deploy_rules.md`의 "스테이징" 절). 하네스는 같은 값을 환경 변수로 받아 `POST /auth/qa-login`으로 사용자를 만듭니다. 값은 출력하지 않습니다.
- 실행: `PYTHONUTF8=1 QA_LOGIN_SECRET=... python qa/harness/run_api_cases.py --base-url http://localhost:8010 [ID ...]`. backend 폴더가 아니어도 되고 httpx만 있으면 됩니다.
- 장소는 `GET /places/search` 결과 중 핀을 만들 수 있는 것에서 고릅니다. 서버 메모리를 비워야 하는 L05.guest11은 SKIP입니다.
- 배포 주소가 생기기 전(#168)에는 로컬 서버를 staging으로 띄워 돌립니다. DB는 `pingo_eval`(개발 DB 복사본)을 씁니다.

`seed_agent_demo.py`는 "핑고 AI 조언" 시연 지도를 만듭니다(#1301). API와 QA 로그인만 쓰고 DB나 시각은 건드리지 않습니다. 정체(기본)와 갈림(`--scenario split`) 두 가지가 있고, `--tick`을 주면 제안이 뜰 때까지 관찰을 돌립니다. 사용법은 파일 머리말과 `docs/demo-guide.md` 장면 8에 있습니다.

`run_llm_cost.py`는 모델 호출 비용을 재는 시나리오입니다(#870, BM 크레딧 설계). 스테이징에서 여행 세 가지(2명, 4명, 6명)를 HTTP로 진행하고 `llm_calls`를 모아 시나리오별, 기능별 호출 수와 토큰, 비용 리포트를 냅니다. 실제 모델을 부르니 돌리기 전에 확인하세요. 스테이징에서는 GitHub Actions의 `llm-cost`를 손으로 돌립니다. 그 밖의 실행 방법은 파일 머리말에 있습니다.

UI 케이스(`layer: ui`)는 FE 5173과 백엔드 8000을 localhost로 띄우고 브라우저로 직접 합니다. 카카오 로그인은 `auth.testing.session_cookie`로 만든 세션 쿠키로 대신합니다.

브라우저 E2E(`e2e/`, #1281)는 UI 케이스 중 핵심 흐름 하나를 자동으로 돕니다. PR마다 GitHub Actions의 `e2e`가 돌고, 로컬에서는 아래처럼 돌립니다.

- 준비: `cd backend && docker-compose up -d`를 하고, E2E 전용 DB를 한 번 만듭니다(`docker exec backend-db-1 psql -U pingo -c "CREATE DATABASE pingo_e2e"`). `contracts`, `frontend`, `e2e`에서 `npm ci`를, `e2e`에서 `npx playwright install chromium`을 합니다.
- 실행: `cd e2e && E2E_PYTHON=<backend 가상환경의 python> npx playwright test`. 마이그레이션, 백엔드(8010), 화면 빌드와 preview(4173), 시드는 설정 파일이 알아서 합니다. 이미 떠 있는 서버가 있으면 그걸 다시 씁니다.
- 개발자 `backend/.env`(실제 키)는 읽지 않습니다. 실패하면 `npx playwright show-trace test-results/<테스트>/trace.zip`으로 봅니다.
