# 루트 리뷰 가이드 — backend/realtime (#369 구독 끊기)

## 구현 범위

- `docs/events.md` "구독을 끊는 경우" 그대로: `map.deleted`를 보낸 뒤 그 지도의 모든 구독(전체·개인), `member.left`를 보낸 뒤 payload `user_id`의 그 지도 구독(전체·개인)을 닫는다. 이벤트를 큐에 먼저 넣고 그다음 기존 `CLOSED` 센티널을 넣는다.
- 판단은 `core.close_after(row) -> CloseScope | None`(순수 함수). `CloseScope(map_id, user_id=None)`이면 지도 전체, `user_id`가 있으면 그 사람만. `member.left`에 `user_id`가 없으면 아무것도 닫지 않는다(지도 전체로 넓히지 않는다).
- `dispatcher._tick`은 조회 → `advance` → `_deliver(emit)`. `_deliver`는 행마다 받을 구독에 넣고, `close_after`가 가리키는 구독에 `CLOSED`를 넣는다. 같은 tick에서 `member.left` 뒤에 온 행은 `CLOSED` 뒤에 쌓여 나간 사람에게 전달되지 않는다.
- 전체 채널 구독도 `user_id`를 기억한다. `Subscription.user_id`와 `Dispatcher.subscribe(user_id=)`가 필수가 됐고, `public_events`가 `get_current_user`를 받는다. 받을 자격(`wants`)은 바뀌지 않았다.
- 변경 파일: `realtime/core.py`, `realtime/dispatcher.py`, `realtime/router.py`, `realtime/tests/` (다른 모듈 파일 없음)

## 테스트 (`tests/test_close_on_leave.py`, `tests/test_core.py`)

- 삭제: 그 지도의 전체 구독은 `map.deleted`를 받은 뒤 끝나고, 개인 구독은 끝나기만 한다. 다른 지도 구독은 그대로
- 나가기·탈퇴 위임(`new_owner_user_id` null/후임, parametrize): 나간 사람의 전체 구독은 `member.left`를 받은 뒤 끝나고 개인 구독도 끝난다. 남은 구성원은 `member.left`를 받고 이후 전체·개인 이벤트도 계속 받는다. 나간 사람의 다른 지도 구독은 그대로
- 같은 tick에서 `member.left` 다음 행은 나간 사람에게 안 간다
- 닫힌 뒤 재구독(`/events`, `/events/me`)은 404 — 멤버십은 `FakeMembership`으로 "나간 뒤" 상태를 준다. 실제 maps 행으로 나가기 → 재구독 404까지 보는 건 `integration/`(루트) 몫으로 남긴다
- 닫는 단계를 빼면 새 테스트가 실패하는 것을 확인했다

## 검증 (PINGO_TEST_DB=pingo_test_rt369)

- `python -m pytest realtime -q` → 39 passed
- `python -m pytest -q` (backend 전체) → 1422 passed, 1 xfailed, 7 deselected

## 남겨 둔 점

- 나간 사람이 다시 초대를 수락하고 새로 구독한 직후, 폴러가 아직 처리하지 않은 예전 `member.left`가 그 새 구독을 닫을 수 있다(폴링 0.5초 안의 일). 닫힌 뒤 EventSource가 재연결하면 구성원이라 200으로 다시 붙으므로 그대로 둔다.

---

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
