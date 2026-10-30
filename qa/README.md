# qa/ — 출시 전 검증 기록

- `cases.yaml` — 케이스 대장(id·layer·scenario·expect·status). 결과가 나올 때마다 status를 고친다.
- `data/` — 합성 테스트 입력(사유 코퍼스 등). 공공데이터 원본·실사용자 데이터는 두지 않는다.
- `harness/` — 실행기. `run_reco.py`(실제 모델 추천 품질), `run_api_cases.py`(API edge). 둘 다 backend 폴더에서 격리 DB(`pingo_eval`, pingo_demo 복사본)를 쓰고 키는 출력하지 않는다.
- `results/<날짜>.md` — 실행 기록(입력→실제 결과→판정). 날짜별로 쌓는다.

실행 예: `cd backend && PYTHONUTF8=1 DATABASE_URL=postgresql://pingo:pingo@localhost:5432/pingo_eval python ../qa/harness/run_api_cases.py [ID ...]`

`run_api_cases.py`는 실제 HTTP로도 돈다(#788). 띄워 둔 서버 주소를 주면 같은 케이스를 그 서버에 보낸다. 배포에서만 생기는 문제(백그라운드 작업, 쿠키, 프록시, 인스턴스마다 따로 세는 상한)를 여기서 본다.

- 서버는 `PINGO_ENV=staging`과 `QA_LOGIN_SECRET`으로 띄운다(`deploy_rules.md`「스테이징」). 하네스는 같은 값을 환경 변수로 받아 `POST /auth/qa-login`으로 사용자를 만든다. 값은 출력하지 않는다.
- 실행: `PYTHONUTF8=1 QA_LOGIN_SECRET=... python qa/harness/run_api_cases.py --base-url http://localhost:8010 [ID ...]`(backend 폴더가 아니어도 된다. httpx만 있으면 된다).
- 장소는 `GET /places/search` 결과 중 핀을 만들 수 있는 것에서 고른다. 서버 메모리를 비워야 하는 L05.guest11은 SKIP이다.
- 배포 주소가 생기기 전(#168)에는 로컬 서버를 staging으로 띄워 돌린다. DB는 `pingo_eval`(개발 DB 복사본)을 쓴다.
`run_llm_cost.py`는 모델 호출 비용 측정 시나리오다(#870, BM 크레딧 설계). 스테이징에서 여행 세 가지(2명·4명·6명)를 HTTP로 진행하고 `llm_calls`를 모아 시나리오·기능별 호출 수, 토큰, 비용 리포트를 낸다. 실제 모델을 부르니 돌리기 전에 확인한다. 스테이징에서는 GitHub Actions의 `llm-cost`를 손으로 돌린다. 그 밖의 실행 방법은 파일 머리말에 있다.

UI 케이스(`layer: ui`)는 FE 5173 + 백엔드 8000을 localhost로 띄우고 브라우저로 수행한다(카카오 로그인은 `auth.testing.session_cookie`로 만든 세션 쿠키로 대체).
