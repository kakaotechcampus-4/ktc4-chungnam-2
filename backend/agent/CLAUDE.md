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

- 명세 2절 "넘지 말 것" 13개 항목. 특히 비공개 데이터(run, 후보, 근거 줄, 제외 목록)를 스냅샷, 도구 결과, 모델 입력에 넣지 않는다
- 모델 호출 추가는 결정 이슈 #509 전까지 하지 않는다. llm 쪽 agent 함수는 고정 응답 스텁으로만 둔다(M0은 모델 없이 shadow)
- `docs/constraints.md`, `docs/events.md`, `docs/api-spec.yaml`의 값과 타입을 임의로 바꾸지 않는다. 바꿔야 하면 루트에 보고한다
- 모델 호출 중에 DB 세션을 열어 두지 않는다(명세 12.6)

## 완료 정의

명세 18절의 단계별 체크리스트와 17절 테스트. 단계마다 이슈가 따로 있다.

## 코드 품질

`docs/code-quality.md` 참고.
