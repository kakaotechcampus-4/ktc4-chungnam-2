# backend/agent

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`. 그다음 명세 `docs/agent-route-v2.md`(지금은 초안이
`drafts/agent-route-v2.md`에 있다, #334).

## 지금 범위 — M0 (동선 에이전트 `course/`)

- 모델 없이 도는 루프 뼈대: 초안 배치, 위반 판정(범위 B — 순서 + 이동시간), 부드러운 목표 점수, 도구 실행과
  검사, 코드 기준선, 루프. 전부 순수 함수이고 DB를 모른다.
- 모델 자리는 `loop.run_loop(decide=...)`로 주입한다. `decide=None`이면 코드 기준선이 끝까지 돈다.
- DB 테이블, API, 이벤트, `llm` 프롬프트는 M1이다 — 정본 문서(`docs/data-model.md`·`api-spec.yaml`·
  `events.md`·`permissions.md`·`errors.md`) 반영과 루트 승인이 먼저다.

## 넘지 말 것

- 하드 위반(휴무·이동시간·구성원 제약) 판정은 `core.py`다. 모델은 도구로만 상태를 바꾼다.
- 하드 확정 위반을 늘리는 채택은 `tools.py`가 거부한다(`WORSENS_HARD`).
- 모델 입력(`loop.turn_input`)에는 별칭만 넣는다 — pin_id, place_id, 좌표, 장소·구성원 이름은 넣지 않는다.
- 영업시간을 모르면 "연다"로 치지 않는다(unknown). 확정 리스트, `visit_order`, `routes`에 쓰지 않는다.
- 다른 모듈의 `models.py`·`service.py`를 import하지 않는다(docs/architecture.md 1절). `common`만 직접 쓴다.
