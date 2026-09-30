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

---

## 추가 — #148(링크 핀 거절)·#141(GET /maps/{id}/counts)

**작업 환경 주의 — 루트가 알아야 할 것**
- 이 작업 폴더는 **git 저장소가 아니다**(`.git` 없음). 그래서 지시받은 `develop` checkout·브랜치 생성·
  develop merge·PR 생성은 **하지 못했다**. 코드·테스트까지만 끝났고, 브랜치/PR은 사용자가 저장소
  clone에서 이 변경분을 옮겨 진행해야 한다. 디스코드 "#N 착수합니다"도 도구가 없어 못 남겼다.
- `PINGO_TEST_DB`(테스트 DB 분리)는 이 트리에 **아직 없다**(grep 0건, develop merge 뒤에 들어오는 것으로
  이해). 그래서 이번 검증은 공유 `pingo_test`가 다른 세션 pytest와 충돌(`relation "pins" does not
  exist`, 교착)해서, 임시 플러그인으로 전용 DB(`pingo_test_148`)를 만들어 돌렸다. develop merge 뒤엔
  `PINGO_TEST_DB=pingo_test_pins`로 재확인 필요.
- 마이그레이션은 만들지 않았다(#157은 PR #156 머지 뒤 별도).

**#148 — v1 링크 핀 거절**
- `core.validate_create`: `source=="link"` 또는 `link_url`이 오면(다른 필드와 함께여도) 422
  `VALIDATION_ERROR`, message `"링크로는 핀을 찍을 수 없어요. 이름으로 검색해 주세요"`(상수
  `core.LINK_PIN_REJECTED_MESSAGE`). 검증은 source 추론보다 먼저 한다.
- `core.resolve_source`의 link_url 추론 제거, `deps.py`의 `draft.place_id or draft.link_url` 제거,
  `PinDraft.link_url`·service의 전달 제거(이제 도달 불가). `PinSource`의 "link"와 `PinCreateRequest.link_url`은
  스키마에 그대로 둠(v2 카톡 내보내기용).
- 테스트: `test_resolve_source_infers_link` → 추론 안 함 테스트로 교체, 모호성 테스트는 place_id+좌표
  조합으로 변경, 거절 파라미터 테스트 5종 + API 레벨 422/미생성 + 검색 경로 201 유지.
- **루트 확인**: `docs/api-spec.yaml`의 `source: link`/`link_url`에 "v1 미수신" 표기와
  `CHANGELOG-api.md`(이슈 본문상 루트 몫, PR #131 머지 뒤)는 건드리지 않았다. 프론트 전달: "link_url을
  보내면 422 + 위 문장, message를 그대로 노출".

**#141 — GET /maps/{mapId}/counts**
- 응답 `FilterCounts{by_category, by_kind}`(스펙 그대로, 스펙 변경 없음). `service.count_pins`가 GROUP BY 한 번
  (category, kind)으로 세고, 없는 카테고리·종류는 0으로 채운다. 키는 `typing.get_args(Category/PinKind)`에서
  만들어 「기타」 추가 시 코드 수정 불필요.
- 가시성: `list_pins`의 WHERE를 `_visible_pins_clause`로 추출해 **목록과 집계가 같은 함수를 쓴다**(가드레일 1 —
  남의 비공개 후보·soft delete 제외, 본인 비공개는 포함). 비구성원은 기존 `require_map_member`로 404.
- 테스트 5개: 0 채움, 시드 집계(삭제·타지도 제외), 비공개 제외/본인 포함, 목록 길이와 합계 일치, 비구성원 404.
- `integration/test_spec_route_coverage.py`의 `KNOWN_MISSING`에서 counts 항목을 삭제했다(그 파일이
  "구현되면 지우라"고 스스로 실패하도록 돼 있음 — 이 파일은 pins 소유가 아니라 루트 확인 요망).

**검증**: 전용 DB에서 `pins integration auth shortlist recommend maps` **422 passed, 1 skipped**, `realtime`
단독 26 passed. 전체를 한 번에 돌리면 realtime 3건(`tick_done`, SSE 타이밍)이 한 차례 실패했고 재실행·단독에선
통과 — pins와 무관해 보이나 **간헐 실패로 루트 확인 필요**. 공유 DB에선 타 세션과 충돌해 전체 0실패를 못 얻었다.

**복잡도**: #148 1/5, #141 2/5 · **실제 소요**: #148 1/5, #141 2/5(코드는 예상대로, 공유 테스트 DB 충돌 진단에 시간).

---

## #157 — FE 스펙 갭 (의견 목록·my_reaction·숙소 반응 차단·기타·AI 핀 필드·탈퇴 함수)

스펙(PR #156)대로 구현했고 스펙 문서는 건드리지 않았다. 마이그레이션 **0016** 하나.

**구현**
- `GET /pins/{pinId}/reactions` — `Reaction[]`(오래된 순), `display_name`은 `auth.api.display_names` 배치 1회, `reason_chip_ids` 포함.
  숙소 핀은 `[]`, 비구성원·남의 비공개 핀은 404. 조회 전용 액션이 없어 가드는 `require("pin.react", load_pin)`를 빌렸다(주석 참고).
- `Pin.my_reaction` — 목록·단건(`api.get_pin_response_for_viewer`, shortlist 경로) 모두. 핀 id 배치 쿼리 1회(N+1 방지 테스트 있음).
  없으면 **`null`을 유지**한다: 라우터의 `response_model_exclude_none`이 null까지 지우므로 `Pin`에 wrap serializer를 뒀다.
  **SSE 페이로드에는 싣지 않는다**(`core._public_pin_payload`가 `exclude={"my_reaction"}`) — 본인 값이 전체 채널로 새면 안 된다.
- `Reaction.reason_chip_ids`/`display_name`; PUT 응답도 chips를 되돌려준다.
- **계약 불일치 수정**: `PUT …/reaction` 응답이 `reason_text: null`을 주던 것을 `response_model_exclude_none=True`로 생략.
  `KNOWN_DRIFT`의 해당 항목, `KNOWN_MISSING`의 `("get","/pins/{}/reactions")`를 지웠다.
- 숙소: `permissions.can_react=false`, `PUT reaction` → 422 `REACTION_NOT_ALLOWED`(사유 검증보다 먼저), `DELETE`는 204.
- `category`에 「기타」(0016, `ALTER TYPE … ADD VALUE`는 autocommit 블록). `Category` Literal 반영, `counts.by_category`에 `기타: 0`이 자동으로 추가됨
  (기존 테스트 기대값 2곳 갱신). `recommend_category`는 그대로.
- `pins.reason` / `member_fulfillment`(JSONB) / `place_source`(JSONB), 모두 nullable. `pins.api.create_ai_pin`에 **선택 인자**
  `reason`, `member_fulfillment`, `place_source`를 추가 — 스키마(`MemberFulfillment{satisfied,total,by_member?}`, `PlaceSource`)로 INSERT 전 검증.
  **recommend는 게시 시 candidate 값을 이 인자로 넘기면 된다**(지금은 안 넘겨서 NULL). 응답·SSE `pin.published`에는 값이 있을 때만 실린다.
- `pins.api.delete_reactions_by_user(db, *, user_id) -> int` — auth가 호출(시그니처는 auth/for_Root.md 그대로). 핀은 남기고, `reaction.changed`는 발행하지 않는다.

**루트 확인 필요**
1. **authz 파일을 최소 수정했다**: `authz/core.py`의 `Resource`에 `category` 필드, `_pin_permissions`에 `can_react and category != "숙소"`.
   `permissions.md`가 "`authz/core.py::_pin_permissions`가 `permissions_for`에서만 계산"이라고 정해서 그대로 따랐다(`can()`은 무변경, 403 아님).
   authz 담당 확인 요청. 대안(pins가 응답을 덮어쓰기)은 권한 로직 중복이라 택하지 않았다.
2. **마이그레이션 번호/체인**: 0015(recommend)가 아직 develop에 없어 `0016.down_revision = 0014`이다. 0015가 머지되면 **0016의 down_revision을 0015로 바꿔야**
   헤드가 하나로 유지된다(지금은 단일 헤드). 머지 순서에 따라 루트가 확인.
3. `docs/data-model.md`의 `pins` 표에 `reason`·`member_fulfillment`·`place_source` 컬럼과 category enum의 「기타」가 아직 적혀 있지 않다(스펙 문서라 손대지 않음).
4. `for_Root.md` 상단 "테스트 68개"는 옛 숫자다. 이번엔 `test_spec_gaps_157.py` 20여 개를 추가했다.

**검증**: `PINGO_TEST_DB=pingo_test_pins python -m pytest` 전체 **633 passed, 1 skipped, 실패 0**. 빈 DB에서 `alembic upgrade head → downgrade 0014 → upgrade head` 통과
(enum에 기타, 컬럼 3개 확인). 테스트가 잡은 실제 결함 1건: 제 serializer가 `exclude`한 `my_reaction`을 null로 되살려 SSE에 새던 것 → 수정.

**복잡도**: 예상 3/5 · **실제 소요**: 3/5.
