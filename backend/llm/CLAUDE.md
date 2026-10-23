# backend/llm

루트 문서를 먼저 읽는다: `/CLAUDE.md`("v1 요청 중 모델 호출은 ② 하나"), `backend/CLAUDE.md`(백엔드 공통), `docs/architecture.md` 2·3절, `docs/constraints.md`(fact_key 목록 = 구조화 출력 스키마의 근거).

## 책임 — v1 요청 중 모델 호출은 ② 하나

이 모듈이 다루는 호출은 아래 3종이지만, v1에서 요청 중 실제로 모델을 부르는 건 ②뿐이다. ③-a-1은 v2, ③-b는 코드(#99, `constraints.md`)다.

1. **②** 사유 → 실격/선호/반경값 구조화 (`recommend`가 근거 조립 시 호출)
2. **③-a-1** 장소 라벨링 — `docs/constraints.md`의 `fact_key` 각각을 판단해 구조화 출력. 불확실하면 `confidence: unknown`으로 반환한다(값을 지어내지 않는다)
   - **검색 기반 보강(2026-09-07 결정, `architecture.md` 3절)**: `seeding`이 비동기 보강 큐에서 이 함수를 부를 때는 검색 도구(우리 소스 재조회 우선, 오픈 웹검색은 최후·안전조건엔 도메인 제한)를 붙여서 호출할 수 있다. 이때도 모델은 라벨만 만든다 — 도구로 늘어난 건 "정보를 더 찾을지" 판단뿐이고, 그 결과에도 근거 대조·unknown 규칙이 그대로 적용된다.
3. **③-b** 선호 순위 채점 — 실격 통과분만 입력받아 순위만 매긴다

**v2 계획 보조 에이전트 호출(#509, 2026-10-15 결정, `docs/agent-v2.md`)**: `agent_diagnose`(도구 콜백 포함), `agent_advise_run`. 신호 순위(`agent_prioritize`)는 #582에서 코드 규칙으로 옮김(agent의 `core.fallback_order`). 요약의 구체화 문장은 고정 문구라 모델 함수가 없다(2026-10-16, #588에서 재검토). 요청 밖 백그라운드 관찰에서 `agent` 모듈이 부르고, 실제 모델과 고정 응답 스텁 중 무엇을 쓸지는 `agent/deps.py`의 Gateway가 고른다. 모델은 사유의 키와 방향을 따로 내지 않는다(②가 한다). 숫자와 인용은 claim 슬롯으로만 쓰고, 검증 실패면 재요청 없이 침묵한다(명세 11절).

지금 열린 것(`llm/api.py`): `agent_diagnose(diagnosis_input, *, tool_runner, planner)`(#532), `agent_advise_run(advice_input, *, tool_runner, planner)`(#587).
- planner는 ②처럼 부르는 쪽이 넘긴다. 스텁 `fixed_diagnosis_planner`(get_reasons를 한 번 부르고 늘 silent), `fixed_advice_planner`(get_run_evidence를 한 번 부르고 늘 silent), 실제 `real_diagnosis_planner`, `real_advice_planner`.
- 추천 막힘 조언은 진단과 같은 도구 왕복이다. 도구는 추천 막힘 전용 4개(`prompts.RUN_ADVICE_TOOLS`), 1회당 `ADVICE_MAX_TOOL_CALLS`(5)회, 프롬프트는 `advise-v4`(반경은 버튼 한 번의 배율 `radius.next_radius_factor`로만 시뮬레이션 #677, 종류는 깔때기 순서와 `ADVICE_CLEAR_DROP` 기준으로 고르고 먼저 근거 줄을 읽는다 #588).
- 도구 대화에는 시간 예산도 있다(#677): 왕복을 시작할 때 대화 시작부터 `DIAGNOSIS_TIME_BUDGET_SEC`(40초), `ADVICE_TIME_BUDGET_SEC`(25초, HTTP 요청 안)가 지났으면 그 왕복은 `tool_choice="none"`이다. 진행 중인 요청은 끊지 않는다. 시계는 `_model_*_planner(clock=)`로 바꾼다.
- 실패(호출 실패, 타임아웃, 스키마 검증 실패)는 예외가 아니라 `AgentCallFailed(reason, detail)`로 돌려준다. 다시 묻지 않는다. 여기서는 스키마 검증까지만 하고, claim·문장·행동 검증은 agent의 core가 한다.
- 도구는 agent가 넘기는 `tool_runner(call_id, name, args)`로만 실행한다. call_id(t1, t2 …)는 이 모듈이 매긴다. 진단 1회당 5회, 그중 structure_reasons 1회(`prompts.DIAGNOSIS_MAX_TOOL_CALLS`, `STRUCTURE_REASONS_MAX_CALLS`)를 넘는 호출은 실행하지 않고 `LIMIT_EXCEEDED`를, 유형에 없는 도구는 `NOT_FOUND`를 도구 결과로 돌려준다. 상한을 다 쓰면 `tool_choice="none"`으로 답을 받는다. 도구 설명과 유형별 허용 목록은 `prompts.AGENT_TOOL_SPECS`, `DIAGNOSIS_TOOLS`이고, map_id는 모델이 고르지 않는다(agent가 채운다).
- gpt-6-luna는 chat.completions에서 도구를 `reasoning_effort="none"`일 때만 받는다(2026-10-15 확인). 진단과 조언 호출은 none 고정이다.
- 평가셋은 `llm/tests/eval_agent/`(지도 상태 20건, 지어낸 사유 글만). 프롬프트를 바꾸면 `python -m llm.tests.eval_agent.run_eval`로 진단을 다시 재고 `prompt_version`을 올린다. 결과(`results/`)는 커밋하지 않는다. 우선순위 케이스는 모델 없이 `core.fallback_order` 기대값 테스트로 돈다(`test_eval_cases.py`, #582).
- 조언 평가셋은 `cases_advice.json`(run 상태 23건, #588)이고 `run_eval --target advice`로 잰다. 도구는 운영 `RunToolContext`가 돌고 데이터만 케이스에서 읽는다(`fixtures_advice.py`). 평가셋이 지금 규칙(대상 판정, 줄 종류, 버튼 규칙)과 맞는지는 모델 없이 `test_eval_advice_cases.py`가 본다.
- 엘리스 strict 구조화 출력은 `oneOf`를 거절한다. 출력 스키마에 discriminator를 걸지 않는다(`schemas.Claim`).

**v2 동선 에이전트 호출(#580, 2026-10-21 결정, #334)**: `course_set_goals`(요청 한 줄 → 목표 6종, 인용은 원문 대조), `course_direct_turn`(지휘: optimize·lock·ask_requester·finish 중 하나를 답변 형식으로 고름, 도구를 `tools`로 주지 않는다). `agent/course`가 사람의 요청으로 부르고, 계산·검증은 그쪽 코드가 한다. 모델 입력은 별칭(p1, d1)만이고 이름·좌표·id를 넣지 않는다. 실패는 재요청하지 않고 코드 기준선이 그 단계를 대신한다.

## 하지 않는 것

- **위 호출(②, ③-a-1, v2 계획 보조 에이전트, v2 동선 에이전트) 외에 모델을 부르지 않는다.** 실패한 호출을 다시 부르지도 않는다. 동선 계산(5-10 「동선 보기」, v2 「AI 코스 짜기」의 코스 계산 모두)에 모델을 쓰지 않는다 — 순수 계산이며 코드가 한다. 모델은 동선 에이전트에서 사람의 말을 목표로 바꾸고 계산 도구를 고를 뿐이다. 카톡 대화 해석에도 쓰지 않는다(5-9, v2에서도 정규식만 — "안정적으로 못 한다"는 기획안 판단 유지).
- 실격 판정 자체(하드 제약 통과/실패 결정)는 하지 않는다 — 모델은 라벨만 만들고, 그 라벨로 거르는 건 `recommend`의 코드다(가드레일 7).

## 넘지 말 것

- ③-a-1의 출력에서 판단이 애매하면 반드시 `unknown`으로 응답하게 프롬프트를 짠다 — 모르는 값을 추측해서 채우면 가드레일 8·9(실격 위반율 0%)가 깨진다.
- 검색 도구를 붙여도 이 규칙은 그대로다. 검색 결과에서 인용한 근거도 원문에 실제로 있는지 코드가 대조하고, 도구를 다 써보고도 불확실하면 여전히 `unknown`이다 — "검색했으니 뭐라도 답해야 한다"는 압박을 프롬프트에 넣지 않는다.
- v1 모델은 GPT-6 Luna `gpt-6-luna`(엘리스 ML API, OpenAI 호환 SDK)다(#12 확정, #372에서 5.6→6, 2026-10-07). 모델 교체와 기획안 13절 반영은 팀 결정 이슈를 통해서 한다.

## 완료 정의

- ②③-a-1③-b 각각의 구조화 출력 스키마 + 프롬프트 + 단위 테스트(평가셋 기반, `docs/constraints.md`의 각 fact_key를 최소 1개씩 커버)
- unknown 응답이 실제로 발생하는 경계 케이스(정보 부족한 후보) 테스트

## 우선순위 — 완성형으로 가지 않는다

FE+BE 코어 루프 데모가 먼저다. `recommend`가 통합을 기다리지 않도록, **먼저 스키마에 맞는 고정 응답 스텁**을 내놓고 `recommend`와 연결한 다음, 남은 기간 동안 품질(정확도)을 아랫단계부터 끌어올린다. 모델 확정(#12) 후 "어느 수준에서 어느 정도 품질이 나오는지" 기준부터 세운다.

## 코드 품질

`docs/code-quality.md` 참고. 이 모듈은 특히 "unknown을 지어내 채우지 않는다"가 리뷰 1순위다.

## 로그 — 실패는 서버 콘솔에 남긴다(#390)

로거는 `pingo.llm`(`llm/client.py`, `llm/service.py`). 레벨은 `LOG_LEVEL`(기본 INFO).
실패는 모델명·배치 크기·예외 클래스·`status_code`·`request_id`·소요 ms(길이 초과면 `completion_tokens`·`finish_reason`)를 warning으로,
성공은 info로 남긴다. **사용자 사유 원문·프롬프트·모델 응답 본문·키·URL은 로그에도 `detail.reason`에도 넣지 않는다** —
`str(예외)`를 쓰지 않고 클래스명과 고정 문구만 쓴다(`str(ValidationError)`에는 입력값이 들어 있다).
