# qa/ — 출시 전 검증 기록

- `cases.yaml` — 케이스 대장(id·layer·scenario·expect·status). 결과가 나올 때마다 status를 고친다.
- `data/` — 합성 테스트 입력(사유 코퍼스 등). 공공데이터 원본·실사용자 데이터는 두지 않는다.
- `harness/` — 실행기. `run_reco.py`(실제 모델 추천 품질), `run_api_cases.py`(API edge). 둘 다 backend 폴더에서 격리 DB(`pingo_eval`, pingo_demo 복사본)를 쓰고 키는 출력하지 않는다.
- `results/<날짜>.md` — 실행 기록(입력→실제 결과→판정). 날짜별로 쌓는다.

실행 예: `cd backend && PYTHONUTF8=1 DATABASE_URL=postgresql://pingo:pingo@localhost:5432/pingo_eval python ../qa/harness/run_api_cases.py [ID ...]`
UI 케이스(`layer: ui`)는 FE 5173 + 백엔드 8000을 localhost로 띄우고 브라우저로 수행한다(카카오 로그인은 `auth.testing.session_cookie`로 만든 세션 쿠키로 대체).
