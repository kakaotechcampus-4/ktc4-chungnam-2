# backend/agent

v2 계획 보조 에이전트. **구현 명세 `docs/agent-v2.md`를 먼저 끝까지 읽는다.** 그다음 루트 문서: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/api-spec.yaml`(agent 태그, `GET /runs/{runId}/advice`), `docs/data-model.md`(agent 절), `docs/events.md`(agent 이벤트 4종), `docs/permissions.md`(`agent.toggle`, `agent.suggestion.resolve`).

## 책임

- 지도를 주기적으로 관찰해 막힌 곳을 찾고(탐지 4종), 사람이 누를 버튼이 붙은 지도 제안을 낸다
- 카테고리별 우리 조건 요약, 추천 막힘 조언
- agent_* 테이블 7개의 쓰기와 정리(`purge_map_data`, `delete_by_user`)

## 하지 않는 것

- 아무것도 직접 실행하지 않는다. 확정, 삭제, 반응 변경, 근거 줄 빼기는 버튼에도 없다
- 사유의 키와 방향 해석(→ `llm` ②). 실격과 점수 계산(→ `recommend`)
- 다른 모듈 테이블 읽기와 쓰기. 다른 모듈 데이터는 `<module>/api.py`로만 읽는다(#113)

## 넘지 말 것

- 명세 2절 "넘지 말 것" 14개 항목. 특히 비공개 데이터(run, 후보, 근거 줄, 제외 목록)를 스냅샷, 도구 결과, 모델 입력에 넣지 않는다
- agent 테이블에 사유 원문을 저장하지 않는다(명세 2절 13번). `reaction_id`로만 가리키고 인용은 응답과 이벤트를 만들 때 렌더한다
- 모델 호출은 #509에서 결정됐지만 단계를 지킨다. M0은 모델 없이 shadow로 돌고, llm 쪽 agent 함수는 M1에서 고정 응답 스텁으로 먼저 통합한다
- `docs/constraints.md`, `docs/events.md`, `docs/api-spec.yaml`의 값과 타입을 임의로 바꾸지 않는다. 바꿔야 하면 루트에 보고한다
- 모델 호출 중에 DB 세션을 열어 두지 않는다(명세 12.6)

## 완료 정의

명세 18절의 단계별 체크리스트와 17절 테스트. 단계마다 이슈가 따로 있다.

## 코드 품질

`docs/code-quality.md` 참고.

## 하위 패키지 `course/` — 동선 에이전트 (#334)

계획 보조 에이전트와 별개 기능이다. 확정 리스트로 여행 코스를 짜는 에이전트로, 명세는 `drafts/agent-route-v2.md`(정본 반영 전,
`docs/agent-route-v2.md` 예정). `course/` 작업은 그 명세를 먼저 읽는다.

- 지금은 M0: 모델 없이 도는 루프 뼈대(`course/core.py`·`tools.py`·`baseline.py`·`loop.py`). 순수 함수이고 DB를 모른다.
- 모델 자리는 `course.loop.run_loop(decide=...)`로 주입한다. `decide=None`이면 코드 기준선이 끝까지 돈다.
- 하드 위반(휴무·이동시간·구성원 제약) 판정은 코드다. 확정 위반을 늘리는 채택은 `course/tools.py`가 거부한다.
- 모델 입력에는 별칭만 넣는다 — pin_id, place_id, 좌표, 장소·구성원 이름은 넣지 않는다.
- DB 테이블·API·이벤트·llm 프롬프트는 정본 문서 반영과 루트 승인 뒤(M1).
