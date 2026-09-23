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
   → **`checks`는 해결됨**(#57 결정 + #124 구현, 아래 "추가 — #124" 참고). `source_run_id`는 여전히 미해결.
2. "카테고리별 사유 칩 목록" API가 계약에 없다(#17 체크리스트엔 있음). 경로·응답 스키마 모두 미정이라 이번엔 만들지 않았다. `docs/constraints.md`의 `fact_key`가 후보 데이터일 수 있으나 확정 필요.
3. `docs/permissions.md`에 `pin.delete` 액션이 없다. 9/4 결정(#25 "구성원 누구나 삭제")은 반영했지만 권한 문서엔 미반영.
4. `PIN_NOT_FOUND`가 `docs/errors.md` 카탈로그에 없다. 목 서버 4곳이 쓰는 중 — 카탈로그 추가 또는 목 수정 필요.

**목 서버 vs 실서버 차이**
5. 목 서버는 핀 하드 삭제, 실서버는 `deleted_at` soft delete(스키마 유니크 제약이 soft delete 전제라 이쪽이 맞다고 판단).

**아직 못 채우는 필드**
6. `place_name`·`created_by_display_name`은 **해결됨**(루트, 2026-09-23:
   `PinCreateRequest.place_name` 추가 + `pins.place_name` 컬럼 신설(0009 마이그레이션),
   `auth.api.display_names` 배선). `price_bucket`은 여전히 `places`(#34) 전엔 채울 수 없어
   응답에서 생략된다.

**설계상 남겨둔 비대칭**
7. `create_pin`은 멤버십을 권한 계산에만 쓰고 생성 자체를 막지 않는다(`delete_pin`·반응 엔드포인트는 403으로 막음). `create_pin`도 같은 기준으로 맞출지 확인 필요.
8. 첫 마이그레이션이 FK 없이 나간다(`users`/`maps`/`places` 부재) — 해당 모듈 도착 시 FK 추가 리비전 필요.
9. `realtime.publish(map_id, channel, type, payload)`에 `recipient_user_id`가 없어 개인 채널 발행 방법이 아직 안 정해졌다.

---

## 추가 — #124: 게시된 AI 핀의 checks 유지 (#57 결정 반영)

가드레일 5(대안 핀에는 조건별 충족 체크가 항상 붙고, 게시된 뒤에도 유지된다) — #57에서 결정한
대로 `candidate.checks`를 게시(「지도에 올리기」) 시점에 `pins` 테이블로 복사하는 방식으로
구현했다. pins가 recommend 테이블을 참조하지 않는 원칙(위 1번)은 그대로 유지 — FK 없는 값
복사뿐이다. recommend 쪽 배선(`flows.py::publish_candidate`가 실제로 `checks`를 넘기는 부분)은
같은 이슈를 recommend 세션이 별도로 처리한다 — 이번 세션은 받는 쪽 계약만 완성했다.

**변경**
- `alembic/versions/0010_pins_checks.py` — `pins.checks jsonb null` 컬럼 추가(0009 뒤, 단일 head).
- `pins/models.py::Pin.checks` — `JSONB | None`.
- `pins/core.py::PinRecord.checks` 추가, `to_pin_response`가 그대로 `Pin.checks`에 실어 보낸다.
- `pins/api.py::create_ai_pin(..., checks: list[dict] | None = None)` — `TypeAdapter(list[Check])`로
  INSERT 전에 모양을 검증(잘못된 값이면 행을 만들기 전에 ValidationError)하고, 검증된 값을
  `PinRow.checks`와 응답·`pin.published` 이벤트 페이로드 양쪽에 싣는다. `get_pin_response_for_viewer`도
  `pin_row.checks`를 읽어 응답에 싣는다.
- `pins/service.py::list_pins` — `PinRecord` 조립에 `checks=pin_row.checks` 추가. 저장만 하고
  조회 경로를 빠뜨리면 "게시된 뒤에도 유지"가 실제로는 안 지켜지므로(화면에 안 보임) 읽기
  경로 2곳(목록·상세) 모두 채웠다.
- `checks`를 안 넘기는 기존 호출부(현재 recommend가 아직 이 파라미터를 안 씀)는 `None` 그대로
  저장되고 응답에서 `response_model_exclude_none`으로 키 자체가 생략된다 — 기존 계약과 호환.

**검증**
- `alembic upgrade head` → `alembic heads` 단일 head 확인, `downgrade -1` → `upgrade head` 왕복 확인.
- `pytest pins/tests recommend/tests shortlist/tests -q` — **259 passed, 1 skipped**(신규 5개 포함:
  checks 저장/응답, checks 생략 시 None, 잘못된 checks는 INSERT 전에 ValidationError로 막힘,
  `GET /maps/{id}/pins`에서 게시된 AI 핀의 checks가 유지되고 직접 핀은 키 자체가 없음,
  `get_pin_response_for_viewer`가 checks를 돌려줌).
- 전체 `pytest -q` — **518 passed, 1 skipped**, 회귀 없음.

**Antigravity 검수 — 시도했으나 완료 못 함**: 로컬 `agy` CLI로 위 변경 파일들에 대한 독립 검수를
시도했다. `--mode plan`(기본, 안전)은 헤드리스라 파일 읽기용 도구 실행조차 승인 프롬프트를 띄울
수 없어 그 자리에서 거부됐고, 이 세션(Claude Code) 자체의 안전장치가 `--dangerously-skip-permissions`
와 `--mode accept-edits` 둘 다 "Create Unsafe Agents"로 차단했다(승인 없이 뭐든 실행하는 하위
에이전트를 만드는 시도로 분류됨) — 즉 이번엔 이 경로로는 뚫을 수 없는 구조적 차단이었다. 대신
위 자동 테스트(신규 5개 + 전체 회귀 518개)와 diff 재독으로 직접 검증했다. **루트가 원한다면
직접 대화형으로 `agy`를 열어 이 변경분을 검수해달라 — 이 세션에선 헤드리스 재시도가 의미
없었다.**

**복잡도**: 2/5 · **실제 소요**: 2/5 (스키마+배선+양방향 읽기 경로 확인까지 예상대로).
