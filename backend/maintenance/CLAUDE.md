# backend/maintenance

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`. 이슈 #168.

## 책임

- `python -m maintenance.run [--dry-run] [--only maps|notifications|guests|llm_calls|idempotency|withdrawn|events|pins]` — 정기 정리를 한 번 돌린다.
  지도, 알림, 게스트, 모델 호출, 멱등 키, 탈퇴 계정, 이벤트, 삭제된 핀(#1063)을 정리한다. 배포 환경의 스케줄러가 이 명령을 부른다.

## 하지 않는 것

- 삭제 로직 (→ 각 모듈의 `api.py`. 여기는 부르기만 한다. 지도는 기존 `maps.api.purge_deleted_maps`(`maps.purge`에 위임)를 재사용하고 그 CLI는 그대로다)
- agent의 일일 정리(`agent.flows.daily_cleanup_if_due`) — 프로세스 안에서 돌아서 넣지 않는다

## 규칙

- 단계마다 별도 세션·커밋 — 한 단계 실패가 다른 단계를 막지 않는다. 실패 로그엔 단계 이름과 에러 타입만(사용자 데이터 금지).
- 단계마다 건수가 0이 될 때까지 되풀이해 부른다(라운드마다 별도 커밋, `MAX_ROUNDS`·`TIME_LIMIT_SECONDS`까지). 상한에 걸려 멈추면 적체
  (backlog) — WARNING 로그, 개인정보 단계(`PERSONAL_DATA_STEPS`, 탈퇴 정리)는 ERROR. 남은 건 다음 실행이 잇는다. 다른 모듈의 배치 상한은
  여기 복사하지 않는다(「또 지웠다」로 안다). 마지막 성공 시각은 로그 `정리 마지막 성공` 한 줄이다(DB 표 없음). dry-run은 롤백이라 한 번만 부른다.
- 단계를 더하려면 `STEPS`에 `(db, now) -> dict[str, int]` 함수를 추가하고 테스트한다.
- 다른 모듈은 `api.py` 함수만 부른다(`backend/CLAUDE.md` 모듈 간 접근).
