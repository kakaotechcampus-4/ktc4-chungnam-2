# backend/notifications

앱 안 알림함과 알림 설정(#470). 먼저 `/CLAUDE.md`, `backend/CLAUDE.md`, `docs/api-spec.yaml`(notifications 태그), `docs/data-model.md`(notifications 절)를 읽는다. 다른 모듈이 부르는 법은 `for_Root.md`.

## 책임

- notifications·notification_prefs 테이블의 쓰기와 조회
- `api.notify`: 수신자별 알림 한 행. 행위자 본인 제외와 꺼 둔 종류 거르기는 여기서만 한다
- 알림 문장(`api.compose_message`), 90일 정리 함수(`purge_old`), 탈퇴 삭제(`delete_by_user`)

## 하지 않는 것

- 푸시·이메일·SSE. 알림에는 실시간 이벤트가 없다(`docs/events.md` 변경 없음)
- 이벤트를 판단하는 일(누구에게 알릴지, 언제 알릴지). 호출하는 모듈이 정해서 수신자마다 `notify`를 부른다
- 다른 모듈 테이블 읽기와 쓰기. 지도 구성원 여부도 보지 않는다(나간 지도의 알림도 남는다)

## 넘지 말 것

- 알림 문장과 테이블에 반대 사유 원문·핀 메모를 넣지 않는다. 문장은 `core.compose_message`의 틀로만 만든다
- `notify`는 commit하지 않는다. 이벤트를 쓰는 호출자 트랜잭션에 참여한다
- 지도 정리(`maps.purge`)가 map_id로 알림을 지우게 하지 않는다. 삭제된 지도의 `map_deleted` 알림이 남은 구성원에게 보여야 한다
- 알림 종류를 늘릴 때는 api-spec `NotificationType`과 `core.TYPES`, `schemas.NotificationType`을 함께 바꾼다(루트가 스펙부터)

## 완료 정의

단위·엔드포인트·마이그레이션 테스트(`pytest notifications`)와 골든 패스 계약 테스트 통과. 호출 연결은 각 모듈 이슈가 한다.
