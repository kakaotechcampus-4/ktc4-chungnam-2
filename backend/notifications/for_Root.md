# 루트 보고 — backend/notifications (#470)

앱 안 알림함과 알림 설정. 푸시·이메일·SSE는 없다. 스펙은 `docs/api-spec.yaml` notifications 태그(PR #538), 스키마는 `docs/data-model.md` notifications 절.

## 구현 범위

- `backend/notifications/`: `models.py`(notifications·notification_prefs), `schemas.py`, `core.py`(문장 틀·커서·설정 합치기), `service.py`, `api.py`, `router.py`, `deps.py`
- 마이그레이션 `0031_notifications`(down: `0030_agent_cursor_drop_gap_seq`, head 하나 유지). 이슈 본문의 `0026`은 옛 초안이다
- 엔드포인트 4개: `GET /me/notifications`, `POST /me/notifications/read`, `GET·PUT /me/notification-prefs`. 권한은 로그인만(멤버십 가드 없음)
- 공유 파일: `main.py`(router 등록), `alembic/env.py`(models import), `integration/conftest.py`(models import)
- `KNOWN_MISSING`·`KNOWN_UNCOVERED`의 알림 4개 항목을 지웠다. 골든 패스는 `integration/test_response_contract.py::test_notification_responses_match_the_openapi_spec`
- `agent/tests/test_migration.py`의 "head가 0030이다" 단언을 "head는 하나이고 0030이 체인에 있다"로 바꿨다(다른 모듈 마이그레이션이 뒤에 붙으면 깨지는 단언이라서)
- 하지 않은 것: pins·maps·recommend의 notify 호출 연결(아래), 탈퇴·정리 작업 연결, `/feedback`(#10)

## 다른 모듈이 부르는 법

import는 `from notifications import api as notifications_api`만 쓴다(models·service 금지). 모두 호출한 쪽 트랜잭션에 참여하고 commit은 호출자가 한다.

### `notify(db, *, user_id, type, map_id, map_title, message, pin_id=None, actor_id=None) -> UUID | None`

- `user_id`는 **수신자**다. 수신자가 여럿이면(예: 지도 삭제 → 구성원 전부) 수신자마다 한 번씩 부른다
- 이벤트를 쓰는 **같은 트랜잭션**에서 부른다(`record_event` 바로 옆). 알림만 따로 커밋하지 않는다
- **거르기는 notify 안에서 한다.** 호출하는 쪽이 미리 거를 필요 없다
  - 행위자 본인: `actor_id == user_id`이면 만들지 않는다. **지금 행위자를 넘기는 자리가 `actor_id`다** — 요청 시그니처에는 없던 인자인데,
    행위자를 모르면 notify가 본인을 거를 수 없어서 키워드 인자(기본 None)로 더했다. 행위자가 없는 시스템 이벤트는 None
  - 꺼 둔 종류: `notification_prefs`에 enabled=false가 있으면 만들지 않는다
  - 걸렀으면 None, 만들었으면 알림 id를 돌려준다
- `type`은 api-spec `NotificationType` 5종: `pin_reaction`, `member_joined`, `owner_changed`, `map_deleted`, `my_ai_pin_published`. 모르는 값은 ValueError
- `map_title`은 만들 때의 제목을 넘긴다(100자 초과는 잘린다). 지도 삭제 알림이 제목을 보여 주려고 남긴다
- `pin_id`는 `pin_reaction`·`my_ai_pin_published`만 넘긴다

### `compose_message(type, *, actor_name=None, map_title=None, reaction=None) -> str`

`message`는 이 함수로 만든다. 문장 틀에 넣을 수 있는 값이 행위자 이름·지도 제목·반응 종류(`like`·`dislike`)뿐이라
**반대 사유 원문과 핀 메모가 알림함에 새지 않는다.** 직접 문장을 쓰지 않는다. 행위자 이름은 `auth.api.display_names`로 얻는다.

### 호출 연결 — 연결 완료(루트, #470 후속)

연결됨: `pin_reaction`(pins `set_reaction`, 작성자가 아직 구성원이고 탈퇴하지 않았을 때만), `member_joined`·`owner_changed`·`map_deleted`(maps 초대 수락·직접 넘기기·나가기·탈퇴 위임·지도 삭제), 탈퇴 시 `delete_by_user`(auth). 반응 종류 값은 API와 같은 `like`·`against`다(`dislike`도 받는다). **`my_ai_pin_published`는 연결하지 않았다** — 「지도에 올리기」는 요청자만 누를 수 있어 올린 사람이 늘 요청자 본인이고 본인 알림은 만들지 않으므로 지금 생길 일이 없다(타입은 스펙에 남겨 둔다). 통합 테스트는 `integration/test_notification_wiring.py`. 아래 표는 설계 당시 기록이다.

| 종류 | 부르는 곳 | 수신자 | actor_id | 비고 |
|---|---|---|---|---|
| `pin_reaction` | pins, 반응 저장 직후 | 핀 작성자 | 반응한 사람 | 자기 핀에 자기가 남기면 notify가 거른다. `reaction`에 `like`/`dislike`. 사유는 넘기지 않는다 |
| `member_joined` | maps, 초대 수락 | 방장 | 들어온 사람 | 방장에게만 |
| `owner_changed` | maps, 직접 넘기기(#468)·나가기·탈퇴 위임 | 새 방장 | 넘긴 사람(탈퇴·나가기면 그 사람) | |
| `map_deleted` | maps, 지도 삭제 | 삭제한 사람을 뺀 구성원 | 삭제한 사람 | 탈퇴로 방장이 없어져 지도가 삭제되는 경우(#369 10번)도 같다 |
| `my_ai_pin_published` | recommend, 「지도에 올리기」 | 그 추천을 요청한 사람 | 올린 사람 | 요청자 본인이 올리면 notify가 거른다 |

### `delete_by_user(db, *, user_id) -> dict[str, int]`

탈퇴(`auth.service.withdraw_user`, #155)가 부른다 — 그 사용자의 알림과 설정을 지운다. 순서 제약 없음. **연결은 auth 세션 몫이다.**
`test_withdraw_cascade`에도 알림 단언을 넣어야 한다.

### `purge_old(db, *, now, older_than_days=90) -> dict[str, int]`

90일이 지난 알림을 읽음 여부와 상관없이 지운다. **호출 연결은 만들지 않았다 — #168(정리 작업) 이슈에 남긴다.**
지도 정리(`maps.purge`, #431)의 `PURGE_STEPS`에는 넣지 않는다: map_id가 같은 알림을 지우면 남은 구성원의 알림함에서
`map_deleted`가 사라진다(`docs/data-model.md`).

## 루트가 정할 것

- `actor_id` 인자 추가(위)가 계약 변경이라면 `docs/CHANGELOG-api.md`가 아니라 이 문서가 정본이다 — HTTP 스펙은 바뀌지 않았다
- 스펙 PR #538이 먼저 머지돼야 이 브랜치가 깨끗하다. 이 브랜치는 그 브랜치를 merge해 둔 상태다
