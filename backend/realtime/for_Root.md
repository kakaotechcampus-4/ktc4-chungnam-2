# 루트 리뷰 가이드 — backend/realtime (#130 서버 종료 처리)

## 구현 범위

- 종료 순서: dispatcher 정지 신호 → 진행 중 `_tick` 완료 대기(상한 `SHUTDOWN_TIMEOUT`) → 열린 SSE 구독 전부 닫기 → 연결 풀 닫기 → 닫힘 상태 해제
- 변경 파일: `main.py`(lifespan), `realtime/dispatcher.py`, `realtime/router.py`, `realtime/tests/test_shutdown.py`

## 수정 완료 — 다른 모듈 TestClient(lifespan) 뒤에 realtime 테스트가 깨지던 문제

- **증상**: `python -m pytest auth realtime` 순서로 돌리면 `test_router_integration.py` 2개 + `test_shutdown.py` 1개 실패.
- **원인 1**: `close_subscriptions()`가 싱글턴 `dispatcher._closing`을 True로 남겼고, lifespan이 끝난 뒤에도 유지돼 이후 `subscribe()`가 이미 닫힌 구독을 받았다.
  - **수정**: 종료가 전부 끝난 시점에 `finish_shutdown()`(`_closing = False`)을 호출한다. `main.lifespan`의 마지막 줄(`engine.dispose()` 뒤).
  - **유지한 동작**: 종료 중(close_subscriptions ~ finish_shutdown 사이)의 새 구독은 닫힌 채로 반환된다.
- **원인 2**: `asyncio.Event()`를 `Dispatcher.__init__`(모듈 import 시점)에서 만들면 TestClient마다 이벤트 루프가 달라 문제가 된다.
  - **수정**: `run_forever()` 시작 시점(실행 중인 루프 안)에서 새로 만든다. 종료되면 `_stop=None`, `_started=False`, `_stop_requested=False`로 되돌려 재시작이 가능하다. `run_forever` 이전에 온 `request_stop()`은 `_stop_requested`로 보관한다.
- **회귀 테스트**: `test_lifespan_leaves_no_closed_state_behind`(lifespan 종료 뒤 새 구독 큐가 비어 있음), `test_run_forever_stops_by_signal_and_can_restart`.

## 검증 (PINGO_TEST_DB=pingo_test_rt)

- `python -m pytest auth realtime -q` → 74 passed
- `python -m pytest auth realtime pins -q` → 187 passed, 1 skipped
- `python -m pytest -q` (backend 전체) → 619 passed, 1 skipped, 실패 0
- 기존 realtime 26개 + `test_shutdown.py` 유지

## 스펙·계약 영향

없음. `docs/api-spec.yaml`·`docs/events.md`·`docs/data-model.md` 변경 없음, 마이그레이션 없음, 다른 모듈 ORM 모델 미사용. `git merge origin/develop` 결과 Already up to date.

## 리뷰 포인트

1. `main.py`의 lifespan `finally` 순서(정지 → 대기 → 구독 닫기 → `engine.dispose()` → `finish_shutdown()`).
2. `Dispatcher`의 정지·닫힘 상태 필드(`_stop`, `_stop_requested`, `_closing`, `_started`)가 종료 뒤 전부 초기값으로 돌아오는지.
