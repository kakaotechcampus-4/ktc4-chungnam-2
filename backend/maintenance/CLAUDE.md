# backend/maintenance

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`. 이슈 #168.

## 책임

- `python -m maintenance.run [--dry-run] [--only maps|notifications|guests]` — 정기 정리를 한 번 돌린다.
  지도(삭제 30일 후), 알림(90일), 게스트(90일 미사용). 배포 환경의 스케줄러가 이 명령을 부른다.

## 하지 않는 것

- 삭제 로직 (→ 각 모듈의 `api.py`. 여기는 부르기만 한다. 지도는 기존 `maps.purge`를 재사용하고 그 CLI는 그대로다)
- agent의 일일 정리(`agent.flows.daily_cleanup_if_due`) — 프로세스 안에서 돌아서 넣지 않는다

## 규칙

- 단계마다 별도 세션·커밋 — 한 단계 실패가 다른 단계를 막지 않는다. 실패 로그엔 단계 이름과 에러 타입만(사용자 데이터 금지).
- 단계를 더하려면 `STEPS`에 `(db, now) -> dict[str, int]` 함수를 추가하고 테스트한다.
- 다른 모듈은 `api.py` 함수만 부른다(`backend/CLAUDE.md` 모듈 간 접근).
