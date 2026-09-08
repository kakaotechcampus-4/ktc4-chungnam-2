# 루트 리뷰 가이드 — backend/pins (#16, #17)

전체 코드를 줄 단위로 다 읽을 필요는 없다. `docs/code-quality.md`의 리뷰 전략(위험도 높은 곳은
자세히, 반복적인 CRUD 보일러플레이트는 가볍게)을 그대로 적용한 순서다.

## 구현 범위

- **#16**: `GET/POST /maps/{mapId}/pins`, `DELETE /pins/{pinId}` — 목록·생성·삭제
- **#17**: `PUT/DELETE /pins/{pinId}/reaction` — 반응 등록/삭제
- 테스트 68개 통과(`pytest pins/tests`), 실제 PostGIS·동시 요청까지 확인됨

## 꼭 읽어야 할 것 (판단이 들어간 곳)

1. **이 파일 아래 "루트 확인·결정 필요" 항목들** — root가 실제로 결정해야 하는 부분.
2. **`pins/core.py`** — 순수 함수만 있어 짧다. 가드레일 1(비공개 후보 유출 금지)·3(반대 사유 필수) 판정이 전부 여기 모여 있다.
3. **`pins/service.py`의 4곳** — 외부 검수(Antigravity·DeepSeek)에서 실제로 버그가 잡혔던 지점.
   - `list_pins`의 WHERE 절 (AND/OR 괄호)
   - `create_pin`의 IntegrityError 분기
   - `set_reaction`의 `ON CONFLICT DO UPDATE` 원자적 upsert (동시 PUT 레이스 방지)
   - `delete_reaction`이 실제로 행이 지워졌을 때만 이벤트를 발행하는 부분
4. **`pins/deps.py`** — 다른 모듈(auth/maps/places/realtime) 자리를 채운 개발용 스텁. 뭐가 아직 가짜인지 알아야 나중에 교체 시점을 판단할 수 있다.

## 가볍게 훑거나 생략해도 되는 것

- `pins/models.py` — `docs/data-model.md` 그대로 옮긴 것
- `pins/schemas.py` — `docs/api-spec.yaml`과 1:1
- `pins/router.py` — 얇은 셸
- `backend/alembic/versions/0001_pins.py` — 마이그레이션
- `pins/tests/` — 68개 테스트 통과로 갈음

## 루트 확인·결정 필요

**계약 갭**
1. `Pin.source_run_id`·`checks`가 `pins` 테이블에 없다. 목 서버는 private 판정을 `source_run_id → run.requested_by`로 하는데, `pins`가 `recommend`를 참조하지 않는 원칙과 충돌 — 이번엔 `created_by` 축으로 구현했다. 스키마 결정 필요.
2. "카테고리별 사유 칩 목록" API가 계약에 없다(#17 체크리스트엔 있음). 경로·응답 스키마 모두 미정이라 이번엔 만들지 않았다. `docs/constraints.md`의 `fact_key`가 후보 데이터일 수 있으나 확정 필요.
3. `docs/permissions.md`에 `pin.delete` 액션이 없다. 9/4 결정(#25 "구성원 누구나 삭제")은 반영했지만 권한 문서엔 미반영.
4. `PIN_NOT_FOUND`가 `docs/errors.md` 카탈로그에 없다. 목 서버 4곳이 쓰는 중 — 카탈로그 추가 또는 목 수정 필요.

**목 서버 vs 실서버 차이**
5. 목 서버는 핀 하드 삭제, 실서버는 `deleted_at` soft delete(스키마 유니크 제약이 soft delete 전제라 이쪽이 맞다고 판단).

**아직 못 채우는 필드**
6. `place_name`/`price_bucket`/`created_by_display_name`은 `places`(#34)·`maps`(#19) 전엔 채울 수 없어 응답에서 생략된다.

**설계상 남겨둔 비대칭**
7. `create_pin`은 멤버십을 권한 계산에만 쓰고 생성 자체를 막지 않는다(`delete_pin`·반응 엔드포인트는 403으로 막음). `create_pin`도 같은 기준으로 맞출지 확인 필요.
8. 첫 마이그레이션이 FK 없이 나간다(`users`/`maps`/`places` 부재) — 해당 모듈 도착 시 FK 추가 리비전 필요.
9. `realtime.publish(map_id, channel, type, payload)`에 `recipient_user_id`가 없어 개인 채널 발행 방법이 아직 안 정해졌다.
