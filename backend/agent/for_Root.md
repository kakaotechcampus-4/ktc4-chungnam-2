# 루트 보고 — backend/agent (#513, M0-1 골격)

## 구현 범위

- `backend/agent/`: `constants.py`(명세 5절 그대로), `models.py`(13절 7개 테이블), `schemas.py`(api-spec Agent*·RunAdvice +
  11.1 모델 출력 스키마), `service.py`, `api.py`, `deps.py`
- 마이그레이션 `0029_agent_tables` (down: `0025_invite_revoke`). head는 0025였고 파일 번호는 0028까지 쓰여 0029로 했다
- `alembic/env.py`에 `import agent.models` 한 줄 (backend/CLAUDE.md 로컬 실행 절대로)
- 테스트 20개(`pytest agent`): 마이그레이션 up/down/up, 부분 유니크 인덱스, FK 동작, purge_map_data, delete_by_user,
  API 스키마를 api-spec으로 검증, 고정 응답 스텁. 백엔드 전체 1692개 통과
- 하지 않은 것: 라우터와 main.py 등록(M1), 스냅샷·탐지기·관찰 루프(#514, #515), maps/purge.py·auth/service.py 연결(#512)

## #512가 연결할 함수

### `agent.api.purge_map_data(db, *, map_ids) -> dict[str, int]`

다른 모듈과 같은 시그니처. 그 지도들의 agent_* 7개 테이블 행을 모두 지운다. agent 테이블은 다른 모듈 테이블을
참조하지 않아서 `maps/purge.py`의 `PURGE_STEPS` 어디에 넣어도 된다(맨 앞 권장).

### `agent.api.delete_by_user(db, *, user_id, map_ids) -> dict[str, int]`

- `map_ids`: `maps.api.lock_member_maps(db, user_id)`가 돌려준 지도 목록을 그대로 넘긴다
- 하는 일
  - `agent_suggestion_views`: 그 사람의 행 전부(지도와 무관)
  - `agent_reason_summaries`: `map_ids` 지도의 요약 전부. 다음 관찰에서 다시 만든다(명세 12.9)
  - `agent_runs`: `map_ids` 지도의 run에서 `tool_calls`를 `[]`, `verification`을 NULL로 비운다. 행과 지표는 남긴다
- 그 사람 항목만 골라내지 않는 이유: tool_calls에는 user_id가 아니라 구성원 별칭만 있고, 반응도 같은 트랜잭션에서 지워진다.
  지도 단위로 통째로 비우는 쪽이 단순하고 빠뜨릴 일이 없다. 잃는 것은 디버깅 로그와 요약(다시 만들어진다)뿐이다
- `verification`도 비운 이유: 모델 quote claim의 text(사유 원문 사본)가 검증 기록에 들어갈 수 있다. 명세 12.9는 tool_calls만
  적었지만 17절 16번은 "agent_runs에 남지 않는다"라서 그쪽에 맞췄다
- 순서 제약 없음. `withdraw_user`에서 `lock_member_maps` 뒤 어디서 불러도 된다

## 루트 확인·결정 필요 (명세 공백)

M0을 막지는 않아서 구현은 끝냈다. M1에서 사유 원문을 실제로 저장하기 전에 정해야 한다.

1. **lock_member_maps 밖의 지도.** `lock_member_maps`는 삭제된 지도를 빼고, 이미 나간 지도는 멤버십이 지워져(#369) 목록에 없다.
   - 삭제된 지도: 정리(30일)까지 그 사람 사유 원문이 tool_calls와 요약에 남는다. 다른 모듈은 반응과 근거 줄을 지도와
     무관하게 user_id로 지운다
   - 나간 지도: 명세 12.9는 "따로 처리하지 않는다"인데, 요약은 새 사유가 3개 쌓여야 갱신되고(나가면 사유 수가 줄어 더
     늦어진다) tool_calls는 30일 남는다
   - 제안: (a) 탈퇴는 삭제된 지도도 포함한 목록을 넘긴다(멤버십은 #245로 남으니 maps.api 함수 하나), (b) 지도 나가기에도
     같은 정리를 그 지도 하나로 부른다. 열람 기록 때문에 나가기용은 `delete_by_user`가 아니라 지도 단위 함수를 따로 연다.
     또는 30일 잔존을 허용한다고 명세에 적는다
2. **사유 원문이 남는 다른 칸.** 명세 12.9는 `agent_runs.tool_calls`와 `agent_reason_summaries.summary`만 적었다. 그런데
   - `agent_suggestions.claims`의 QuoteClaim.text, `agent_suggestions.advice`의 렌더 결과(`{cN}`을 DB 원문으로 바꾼 문장, 11.2)에도
     원문이 들어간다. agent_suggestions에는 보존 기한도 없다(agent_runs만 30일)
   - `agent_run_advice`의 예시 문장에 근거 줄 원문이 들어갈 수 있다. recommend는 탈퇴 때 근거 줄을 지운다
   - 제안: 저장에는 원문 대신 reaction_id 참조만 두고 GET 응답을 만들 때 렌더하거나, `delete_by_user`가 그 지도들의 제안과
     조언에서 quote를 지우게 한다. 어느 쪽이든 M1 시작 전에 명세 12.9와 data-model에 적어야 한다
3. **원문을 넣지 않는 칸.** `signals`, `blocked`, `priority`, `outcome_detail`에는 사유 원문을 넣지 않는다는 규칙을 명세에 한 줄
   두면 정리 범위가 지금 칸으로 닫힌다

## 구현 메모

- `deps.py`는 아직 `common.adapters.select`를 쓰지 않는다. main.py가 agent를 import하지 않는 동안 포트를 등록하면 등록 여부가
  테스트 순서에 따라 달라져 `common/tests/test_adapter_assembly.py`가 깨진다(실제로 깨지는 것을 확인했다). M1에서 router를
  main.py에 올릴 때 `select("agent.LlmGateway", ...)`로 바꾸고, real 구현이 그때도 없으면 그 테스트의 `MISSING_REAL`에 올린다
- 고정 응답 스텁은 우선순위만 받은 순서대로 돌려주고 나머지는 전부 silent다. 지어낸 문장이 나갈 길이 없다
- `AgentActionParams`는 채우지 않은 키를 직렬화에서 뺀다. api-spec의 params 키는 null을 받지 않는데, 응답 전체에
  exclude_none을 걸면 null이 필수인 `AgentSuggestion.category`·`analysis`까지 빠지기 때문이다
- 상태값(trigger, outcome, diagnosis, status)은 명세대로 text이고 CHECK 제약은 두지 않았다. 허용 값은 `models.py`의 튜플에 있다
- 마이그레이션 테스트는 `<PINGO_TEST_DB>_agent_mig` DB를 새로 만들어 0001부터 head까지 올리고 지운다. alembic.ini를 넘기면
  env.py의 `fileConfig`가 기존 로거를 꺼서 같은 실행의 caplog 테스트가 깨지므로 ini 없이 Config를 만든다

---

# 루트 보고 — backend/agent (#514, M0-2 스냅샷·탐지기·정책)

## 구현 범위

- `snapshot.py`: `build(db, map_id, now) -> Snapshot | None`. maps·pins·shortlist·recommend의 `api.py`만 부른다. 세션과
  격리 수준은 받기만 한다(#515가 정한다). `latest_seq`·`latest_event_at`은 None(#515)
- `core.py`(순수): 기준 시간, 탐지기 4종과 `detect_all`, `make_signal`·`fingerprint`·`evidence_hash`, `check_policy`,
  `dismissal_streak`·`backoff_until`, `model_cap_reached`, `kst_date`·`kst_day_start`, `fallback_order`, `next_check_at`,
  `parse_policy`·`load_policy`
- `priority_policy.yaml`: 명세 7절 초안 그대로
- 테스트 75개(17절 1, 4, 5, 6번과 스냅샷 조립). agent 95개, 백엔드 전체 1789개 통과
- 하지 않은 것: run_tick, observe_map, 커서, lease, 저장(#515). compare_reasons와 충돌 종류(M1 도구). 다른 모듈 파일 수정 없음

## 명세와 다르게 한 것

1. **`build`가 None을 돌려줄 수 있다.** 지도 행이 없으면(정리까지 끝남) None. #515는 map_deleted와 같이 다루면 된다.
   삭제된 지도는 지도 정보만 담고 나머지는 비운 Snapshot이다(어차피 바로 끝난다)
2. **KST는 고정 +9시간.** `zoneinfo("Asia/Seoul")`는 Windows에서 tzdata 패키지가 있어야 하는데 requirements에 없다.
   한국은 서머타임이 없어 같은 값이다. `DAY_BOUNDARY_TZ` 상수는 그대로 두었다
3. **`next_check_at(snap, history, now, th)`** — 명세의 `signals` 인자를 뺐다. 후보를 스냅샷에서 다시 계산하고, 이미
   지난 시각은 빼서(지금 신호로 이미 잡힌다) 미래 시각 중 가장 이른 것만 돌려준다
4. **features의 `recent_dismissals`는 `check_policy`가 채운다.** 탐지기는 이력을 모르므로 0으로 두고, 정책을 통과한
   신호에만 연속 닫힘 수를 넣는다
5. **`affected_members` 정의(명세에 없음)**: stall은 🚫를 남긴 사람 수, split은 그 핀에 반응한 사람 수, no_reaction은
   조건에 걸린 구성원 수, category_gap은 구성원 수
6. **핀 근거의 evidence_hash 재료**: 반응은 (reaction_id, like/against, updated_at). no_reaction은 (pin_id, "pin",
   created_at), category_gap은 (pin_id, "confirmed", added_at). 시각은 UTC로 맞춰 해시한다
7. **확정 항목은 삭제되지 않은 핀의 것만 담는다.** `list_items_for_agent`는 삭제된 핀의 항목도 주지만, 확정 핀을 지우면
   항목도 빠지고(#235) 6절이 "삭제되지 않은 핀 기준"이라 걸렀다
8. **`check_policy`는 신호 하나에 이유 하나만 남긴다**(12.3 순서에서 처음 걸린 것). 활성 제안이 있으면 전부 active_exists
9. 정책 이력 타입 `core.PastSuggestion`·`core.History`(suggestions 최신순, model_runs_today)를 core에 두었다. #515의
   `service.load_history`가 이 모양으로 채운다. model_runs_today는 `started_at >= core.kst_day_start(now)`로 센다

## 테스트 환경

- `agent/tests/conftest.py`가 다른 모듈 models를 import하고 postgis 확장을 만든다(스냅샷 테스트가 pins·maps·recommend·
  shortlist 행을 넣는다). integration/conftest.py와 같은 방식이다

## 읽기 함수 요청

없음. #522로 연 함수로 충분했다. `list_reasoned_reactions`는 카테고리가 필수라 관찰 대상 카테고리마다 한 번씩(지금 3번) 부른다.

---

# 루트 보고 — backend/agent (#515, M0-3 관찰 루프)

## 구현 범위

- 마이그레이션 `0030_agent_cursor_drop_gap_seq` (down: `0029_agent_tables`). agent_cursors.gap_seq 삭제(#525)
- `service.py`: claim_maps, release_lease, advance_cursor, load_history, expire_suggestions, supersede, insert_suggestion,
  insert_run, set_run_outcome, delete_old_runs
- `flows.py`: run_tick, observe_map, daily_cleanup_if_due. `loop.py`: 개발용 반복 작업 start/stop
- `core.py`: has_recent_event, find_superseded, recheck, choose_top, signal_record. `PastSuggestion.evidence_hash` 추가
- `snapshot.build`가 `latest_seq`, `latest_event_at`을 채운다(`realtime.api.latest_seq_by_map`, 같은 REPEATABLE READ 트랜잭션)
- `main.py` lifespan: import 1줄, `agent_loop.start()` 1줄, `await agent_loop.stop(SHUTDOWN_TIMEOUT)` 1줄(dispatcher 정지 앞).
  `AGENT_LOOP_IN_PROCESS=False`(기본)면 아무것도 띄우지 않는다
- 테스트: agent 131개(새로 36개), 백엔드 전체 1825개 통과

## outcome이 남는 경우

| outcome | 언제 |
| --- | --- |
| map_deleted | 지도가 삭제됐거나(#369) 행이 없음(build가 None). 커서만 올리고 next_check_at은 null |
| trip_ended | KST 오늘 > end_date. 위와 같다(마지막 날까지는 관찰) |
| no_signal | 탐지된 신호 없음 |
| blocked | 신호가 모두 정책에 막힘, 또는 저장 때 다른 관찰이 먼저 활성 제안을 넣음(active_exists) |
| silent | 1순위가 모델 유형(stall, split). M0은 모델 단계를 건너뛴다. outcome_detail `{"skipped": "model_step", ...}` |
| stale | 저장 직전 재확인에서 신호가 사라졌거나 evidence_hash가 바뀜 |
| suggested | 코드 유형 초안 저장. 제목·문장·버튼은 빈 값(M1 렌더), shadow=AGENT_SHADOW_MODE |

저장 트랜잭션 맨 앞 `lock_map_if_alive`가 False면 agent_runs 행도 남기지 않는다(커서도 그대로).

## 명세와 다르게 한 것

1. `claim_maps(db, now, *, limit)` — service 규칙대로 db를 받고 커밋은 flows가 한다. (map_id, trigger)를 돌려준다
   (바뀐 지도면 activity, next_check_at으로 잡혔으면 time)
2. `daily_cleanup_if_due`는 flows에 두었다. "오늘 했나"를 프로세스 메모리(KST 날짜)에 두어서다. 인스턴스가 여럿이면
   하루 몇 번 돌 수 있지만 지우기만 해서 결과는 같다. service는 `delete_old_runs`. `decided_within_24h` 채우기는 하지 않았다(M1 지표)
3. M0 1순위: fallback_order의 1순위가 모델 유형이면 코드 유형으로 내려가지 않고 silent로 남긴다. M1과 같은 빈도를
   shadow로 보려는 것이다. 유형별 발동 빈도는 agent_runs.signals에 모든 신호가 남아 있어 그대로 셀 수 있다
4. 저장 순서: insert_run을 insert_suggestion보다 먼저 한다(제안의 run_id FK). 제안이 충돌하면 그 run의 outcome을
   blocked로 고친다(set_run_outcome)
5. 재확인: `snapshot.load_evidence` 대신 저장 트랜잭션 안에서 `snapshot.build`를 다시 부르고 `core.recheck`가
   detect_all을 다시 돈다. 기준 시간은 관찰 때 값을 쓴다
6. map_deleted와 trip_ended도 agent_runs 행을 남긴다(명세 의사코드는 커서만). shadow 로그에서 끝난 지도가 얼마나
   잡히는지 보려고. 정리된 지도(build None)는 커서 행이 없어 커서는 건드리지 않는다
7. next_check_at 후보에 방금 넣은 제안의 expires_at을 더했다(이력에는 아직 없어서)
8. 제안 created_at은 DB now()가 아니라 관찰 시각(now)이다. no_reaction 하루 1회와 백오프가 같은 시계를 본다
9. shadow를 꺼도 M0은 이벤트를 내지 않는다(agent.suggested, agent.resolved는 M1). 그 자리에 주석만 두었다

## 루트 확인 요청

1. `docs/data-model.md` 315행, `docs/agent-v2.md` 13절의 gap_seq 주석 → "0030에서 지웠다"로 갱신
2. `docs/agent-v2.md` 12.4 의사코드에 위 4~7번(run 먼저, build 재호출, 끝난 지도도 run 기록)을 반영할지
3. `AGENT_LOOP_IN_PROCESS`는 명세대로 상수라 개발자가 켜려면 constants.py를 고쳐야 한다. 환경 변수로 받으려면
   `common/settings.py`에 칸이 필요해서 손대지 않았다
4. 비용 메모: 관찰 한 번마다 `latest_seq_by_map`(24시간 전 지도 DISTINCT ON)을 한 번 더 부른다(claim 1번 + 지도마다
   1번, 초안이 있으면 재확인에서 1번 더). tick당 최대 21번이다. 측정해 보고 무거우면 realtime에 지도 하나용 함수를 요청한다

---

# 루트 보고 — backend/agent (#531, M1-1 코드 유형 제안을 화면까지)

## 구현 범위

- shadow를 유형별로: `constants.AGENT_SHADOW_MODE`(bool)를 지우고 `SHADOW_DIAGNOSES = MODEL_TYPES`. 코드 유형은
  shadow=False로 저장하고 이벤트를 낸다. 모델 유형은 #534에서 이 목록에서 뺀다
- `core.render_template(signal) -> Draft`(6.4, 6.5), `core.render_suggestion`(슬롯 채우기), 이벤트 페이로드 3종,
  `core.agent_state`, `core.settings_view`
- `router.py`(5개 경로), `loaders.py`(제안 id → 지도 Resource), main.py에 `include_router` 1줄과 import 1줄
- `deps.py`: `select("agent.LlmGateway", settings.llm_mode, ...)` 등록
- 이벤트(같은 트랜잭션, `record_event`), 전부 shadow가 아닌 제안만

| 이벤트 | 내는 곳 |
| --- | --- |
| agent.suggested | `flows.observe_map` 7단계, `insert_suggestion`이 넣은 뒤 같은 트랜잭션에서 렌더 |
| agent.resolved(expired) | `flows.observe_map` 1단계 `expire_suggestions` |
| agent.resolved(superseded) | `observe_map` 7단계 `supersede`, `change_settings`(끌 때) `supersede_active` |
| agent.resolved(accepted, 버튼 type) | `flows.accept` |
| agent.resolved(dismissed) | `flows.dismiss` |
| agent.settings_changed | `flows.change_settings`. 끌 때는 agent.resolved 다음에 낸다 |

- 테스트: agent 169개(새로 38개: test_core_render, test_router, test_flows 추가분), 백엔드 전체 1870개 통과
- integration: `KNOWN_MISSING`, `KNOWN_UNCOVERED`에서 5개 경로를 지우고 `test_agent_endpoints_match_the_openapi_spec`를
  넣었다. `/runs/{runId}/advice`는 M2라 그대로

## 템플릿 문구 최종본

| 유형 | 제목 | 확인된 것(is_guess=false) | 버튼 |
| --- | --- | --- | --- |
| no_reaction | 아직 확인되지 않은 핀이 {n}개 있어요 | 핀 이름 한 줄씩(db 핀은 장소 이름, 실시간 핀은 검색어) | 미확인 핀 보기(show_pins, `pin_ids`) |
| category_gap | 확정 리스트에 {category}가 아직 없어요(받침이면 "이": 음식점이) | 확정 {n}곳 중 {category} 0곳 | {category} 추천 받기(open_recommend) + {category} 핀 보기(show_pins). 추천 대상이 아니면 첫 버튼이 {category} 검색(search_place) |

저장 모양: title과 advice는 슬롯 문장(`{c1.value}`, `{c2}`), claims는 count claim과 핀 ref claim. 예 — no_reaction의
advice는 `[{"slot_text": "{c2}", "is_guess": false}, ...]`, claims는 `[{"id":"c1","kind":"count","metric":"unseen",...},
{"id":"c2","kind":"ref","object":"pin","ref_id":"<pin_id>"}, ...]`. 핀 이름은 저장하지 않는다.

## 명세나 계약과 다르게 한 것

1. **`render_template(signal)`** — 명세 12.4는 `(top, snap)`. 코드 유형은 신호의 근거 id 수와 카테고리만으로 정해지고
   이름은 렌더 때 읽어서 스냅샷이 필요 없다
2. **title도 슬롯 문장으로 저장한다.** data-model.md("슬롯 문장과 검증 통과 claim. 렌더는 응답 때")를 따랐다. 명세 13절
   SQL 주석과 models.py 주석은 "렌더 결과"였다(models.py는 고쳤다)
3. **no_reaction 제목의 n은 저장 때 값이다.** 핀이 지워져 이름 줄이 빠져도 n은 그대로다. 다음 관찰에서 evidence_hash가
   바뀌어 superseded가 되므로 길어야 한 tick이다. 장소 이름을 찾지 못한 db 핀도 지어내지 않고 줄을 뺀다
4. **show_pins에 `unseen_only`를 넣지 않았다.** 그 핀들은 "누군가" 확인하지 않은 핀이라 보는 사람 기준 미확인과 다르다.
   `pin_ids`만 준다. 버튼 params의 pin_ids는 지워진 핀을 걸러 내지 않는다(문장만 뺀다)
5. **만료 시각이 지난 활성 제안**: 관찰이 expired로 바꾸기 전에도 GET은 null, accept·dismiss는 409(가드 UPDATE에
   `expires_at > now`). agent.resolved(expired)는 다음 관찰이 낸다
6. **같은 값의 PUT settings**는 쓰지도 이벤트를 내지도 않고 지금 값을 200으로 돌려준다
7. **모드 끄기와 관찰 저장의 경합**: `change_settings`가 `maps.api.lock_map_if_alive`로 지도 행을 먼저 잠그고, 관찰 저장
   트랜잭션은 잠근 뒤 모드를 다시 본다. 꺼져 있으면 넣지 않고 outcome=blocked, 이유 `mode_off`(12.3 목록에 없는 새 값)
8. **view의 가드**: permissions.md에 열람 액션이 없어 `require_with_principal("agent.suggestion.resolve", ...)`로
   멤버십을 본다(pins의 PinToRead가 pin.react를 빌리는 것과 같은 사정). 구성원 누구나 가진 액션이라 결과는 같다
9. **422 detail**: `{"action_index": 9, "actions": 2}`
10. **Gateway real 구현**: llm.api의 agent 함수가 #532 전이라 `RealAgentLlmGateway`는 부르면 NotImplementedError다.
    real을 None으로 두면 로컬 .env의 `LLM_MODE=real`에서 select()가 import 때 ConfigError를 내 서버가 뜨지 않는다. M1-1은
    Gateway를 부르지 않는다
11. **다른 모듈 파일 수정 1건**: `common/tests/test_adapter_assembly.py`의 `MISSING_REAL`에 `"agent.LlmGateway": "#532"`
    한 줄. 그 테스트는 등록된 포트 집합과 이 목록이 같아야 통과해서, select() 등록과 테스트 통과를 함께 하려면 피할 수 없다
12. **agent 자기 이벤트로 한 번 더 관찰한다.** agent.suggested·resolved도 event_log seq를 올려 다음 tick에 그 지도가
    activity로 다시 잡힌다. 그 관찰은 활성 제안에 막혀(blocked) 이벤트를 내지 않으므로 거기서 멈춘다(테스트로 고정).
    커서를 자기 이벤트 seq까지 올리면 그 사이 늦게 커밋된 사용자 이벤트를 놓칠 수 있어 그렇게 하지 않았다. 비용이 문제면
    realtime에 "agent.* 제외 최대 seq"를 요청하는 쪽이 맞다

## 루트 확인 요청 (문서 갱신)

1. `docs/agent-v2.md` 5절 `AGENT_SHADOW_MODE` → `SHADOW_DIAGNOSES`, 12.4 의사코드(shadow 판단, render_template 인자,
   모드 재확인), 13절 title 주석, 15절 마지막 문장, 17절 15번
2. `docs/agent-v2.md` 12.3 blocked 이유에 `mode_off` 추가
3. `docs/events.md` 38행 "shadow 기간(`AGENT_SHADOW_MODE`)", 58행 "서버 구현 전이라 아직 발행되지 않는다" → 코드 유형은
   #531부터 발행, 모델 유형은 #534까지 shadow
4. `docs/api-spec.yaml` agent 태그 설명과 951행 주석의 "실서버 구현 전(KNOWN_MISSING)" → 5개 경로 구현됨(advice만 M2)
5. FE(#516, #536)에 알릴 것: 실서버에서 코드 유형 제안이 나온다. view는 이미 처리된 제안도 204, accept 범위 밖 422,
   만료 시각이 지난 제안은 GET에서 null이고 accept·dismiss 409


---

# 루트 보고 — backend/agent (#533, M1-2 도구, 검증, 우선순위 보정, 모델 단계 연결)

## 구현 범위

- llm과 맞추기(#532 보고대로)
  - `deps.py`: `ToolRunner = llm.api.ToolRunner`(call_id, name, args). Gateway의 prioritize와 diagnose는 `... | AgentCallFailed`를
    돌려준다. Fixed는 fixed planner, Real은 real planner를 `llm.api.agent_*`에 넘긴다. structure_reasons가 쓸 ②도 Gateway에
    `structure(raw_reasons)`로 두었다(Fixed는 passthrough_planner, Real은 real_evidence_planner)
  - `schemas.py`: 11.1 사본(CountClaim … PriorityOutput)을 지우고 `llm.schemas`에서 가져온다. SummaryOutput과 RunAdviceOutput은
    llm 함수가 M2라 agent에 남겼다(llm의 Claim, AdviceLine, Action을 쓴다)
  - `constants.py`: `DIAGNOSIS_MAX_TOOL_CALLS`, `STRUCTURE_REASONS_MAX_CALLS`를 지웠다(강제는 llm)
- `tools.py`: 도구 8개, `ToolContext.run`(tool_runner), 기록용 `redact`, ② 결과 캐시 `StructureCache`
- `core.py`: `priority_input`, `apply_priority_rules`, `priority_mode`, `choose_top`의 모델 경로, `diagnosis_input`,
  `compare_reasons`(6.3), `render_analysis`, `verify_diagnosis`(11.2, `count_metric`, `resolve_path`), `failed_outcome`
- `flows.observe_map`: 5단계(우선순위 모델), 6단계(진단과 검증). Gateway는 인자로 받고 없으면 `deps.get_llm_gateway()`
- `models.RUN_OUTCOMES`에 `model_failed`(data-model.md에는 #532에서 이미 있다. CHECK 제약이 없어 마이그레이션 없음)
- `service.load_history`: 직전 관찰(activity, time)의 `priority`를 `History.last_priority`로
- 테스트: agent 169개 → 272개(새로 103개: test_core_verify 44, test_core_priority 29, test_tools 15, test_flows_model 15).
  기존 3개 고침(choose_top 기록 모양, gap 두 개 지도의 used_model, 스텁 진단의 outcome_detail과 도구 기록)

## 도구별 반환 예시

인자는 llm/for_Root.md(#532) 표대로 받고 map_id는 agent가 채운다. 목록은 상위 30개와 `total`. 구성원은 별칭만.

| 도구 | 반환 |
| --- | --- |
| get_map_overview `{}` | `{dday: 30, member_count: 3, categories: [{category: "음식점", pins: 1, confirmed: 0}, …], last_activity_at: "…"}` |
| get_activity `{since}` | `{since, counts: {pin: 0, reaction: 2, shortlist: 0}, distinct_actors: 2, median_gap_minutes: 300.0}`. since가 null이면 24시간 전 |
| get_reaction_matrix `{category}` | `{category, members: ["m1","m2","m3"], pins: [{pin_id, name: "성수 칼국수", reactions: {m1: "like", m2: "like", m3: "against"}}], total}`. 실시간 핀 name은 검색어, null은 미확인 |
| get_reasons `{pin_ids, category, types}` | `{reasons: [{reaction_id, pin_id, category, type, text, chips: [{chip_id, label, fact_key, wants}], member_alias: "m3", updated_at}], total}`. 최근 것부터, 삭제된 핀의 사유 포함 |
| structure_reasons `{reaction_ids}` | `{reasons: [{reaction_id, type, lines: [{fact_key: "parking_available", wants: true, badge: "required"}, {fact_key: "spacious", wants: true, badge: "required"}]}], total, not_found: [...]}`. 글은 ②, 칩은 칩 표 |
| compare_reasons `{pin_id, category}` | `{pin_id, category, conflict_type: "same_axis", keys: [{fact_key: "spacious", want: [{reaction_id, side: "against"}], avoid: [{reaction_id, side: "like"}]}], total}` |
| get_place_facts `{place_ids, fact_keys}` | `{facts: [{place_id, fact_key: "quiet", value: true, confidence: "known"}, {…, value: null, confidence: "unknown"}], total, not_found: ["pl_elsewhere"]}` |
| get_readiness `{category}` | `{category: "음식점", ready: true, answered_count: 2, required_count: 1}` |

오류: 유형에 허용되지 않은 도구나 없는 대상(카테고리, 지도)은 `{"error": "NOT_FOUND"}`, ②가 실패하면 `{"error": "UNAVAILABLE"}`.

기록(agent_runs.tool_calls): `[{call_id: "t1", name, args, result, ms}]`. result 안에서 `reaction_id`와 같이 있는 `text`는
`text_len`(글자 수)로 바뀐다. 모델에 준 원래 결과는 `ToolContext.results`에 메모리로만 두고 검증(tool_result claim)에 쓴다.

## outcome 매핑 (6단계)

| 상황 | outcome | outcome_detail | verification |
| --- | --- | --- | --- |
| AgentCallFailed reason=invalid_schema | invalid_schema | `{signal_id, diagnosis, reason, detail}` | null |
| AgentCallFailed reason=timeout, call_failed | model_failed | 같음(detail은 예외 클래스명) | null |
| decision=silent, unknown | silent, unknown | `{signal_id, diagnosis, decision}` | `{decision}` |
| 검증 2단계(신호 불일치), 7단계(성립 실패) | invalid_claims | `{signal_id, diagnosis, decision: "suggest"}` | 단계별 내역과 `failed_step` |
| 검증 통과 | suggested(모델 유형은 shadow=true, 이벤트 없음) | null | 단계별 내역 |
| 통과 뒤 저장 직전 재확인 실패 | stale | | |

`used_model`은 우선순위나 진단을 부른 관찰이면 true다(호출이 실패해도). 한 관찰에서 둘 다 불러도 행 하나라 1회다.
`ToolRunnerError`(agent 도구 쪽 버그)는 잡지 않는다 — observe_map이 실패하고 run_tick이 로그를 남긴다(agent_runs 행 없음).

## 검증 단계별 테스트 수 (test_core_verify.py, 매개변수 포함)

| 단계 | 테스트 | 내용 |
| --- | --- | --- |
| 통과 | 2 | split(quote text를 버림, analysis), stall(count 없이 성립) |
| 1 decision | 2 | silent, unknown |
| 2 진단 성립 | 2 | signal_id, diagnosis가 다름 |
| 3 claim 대조 | 11 | 지어낸 count(→ 7단계 invalid_claims), 원문에 없는 quote, 사유 글 없는 반응 quote, 없는 ref, tool 값 다름(True와 1), 없는 path, 없는 call_id, 없는 핀 count, 잘못된 id, 목록 경로와 category·map·unseen 통과, 같은 id 두 번 |
| 4 구조 대조 | 0 | 요약 전용(진단은 `structure: "skipped"`) |
| 5 문장 | 16 | 슬롯 밖 숫자 2, 표시 이름, 별칭, 금지 표현 2(공백 무시), 슬롯 밖 원문 옮겨 쓰기 2, 없는 claim 슬롯, 슬롯 종류 2, 깨진 슬롯, 없는 basis, 빈 문장, 제거된 claim을 가리킴, 한 글자 이름은 보지 않음 |
| 6 행동 | 7 | split에 search_place, open_evidence, 숙소 open_recommend, 빈 basis, 없는 basis, 없는 핀 show_pins, 중복 제거와 버튼 이름 |
| 7 성립 | 2 | 남은 것 없음, 행동만으로 성립 |

그 밖: 진단 입력(비공개 데이터, user_id, 사유 글 없음) 1, failed_outcome 1. 관찰 흐름(test_flows_model.py)에서 outcome 매핑 7,
17절 7번(핀 확정, 반응 수정) 2, 17절 11번 1, 모델 사용 1회와 순위 재사용 1, 상한과 우선순위 실패 2, 저장된 행에 사유 글 없음
(shadow 제안 저장 테스트 안).

## 명세와 다르게 한 것 (또는 명세에 없어 정한 것)

1. **모델 유형 제목은 코드 문구다.** DiagnosisOutput에 제목 칸이 없다. stall "{카테고리} 후보가 반대 의견 뒤로 멈춰 있어요",
   split "의견이 갈린 핀이 있어요". 버튼 이름도 모델 Action에 label이 없어 코드가 정한다(코드 유형과 같은 문구, pin_ids
   show_pins는 "핀 보기")
2. **우선순위 입력은 fallback_order 순서로 넘긴다.** 고정 응답 스텁이 받은 순서 그대로라, 이렇게 해야 dev에서도 M1-1과 같은
   1순위가 나온다(그대로 넘기면 탐지 순서라 no_reaction이 category_gap보다 앞에 왔다)
3. **순위 재사용 조건**: 직전 관찰(activity, time 중 최신 행)의 priority.source가 model이나 reused이고 fingerprint 집합이 같을 때.
   직전이 fallback(실패, 상한)이면 재사용하지 않는다. 재사용은 상한보다 먼저 본다(부르지 않으니까).
   priority 기록에 `source`(single|model|reused|fallback), `fingerprints`(final_order 순서), `fallback_reason`을 더했다
4. **apply_priority_rules 보정 순서**: 모르는 id 버림 → 중복 버림 → 빠진 신호를 fallback_order로 뒤에 → always_first 앞으로 →
   1순위가 never_first면 아닌 첫 신호를 앞으로. corrections에 type별로 남긴다
5. **compare_reasons에서 같은 키, 같은 방향은 unclear.** 6.3 표에 없는 경우다. 예: ♥ "조용해서 좋아요"(quiet 원함)와 🚫 칩
   「시끄러워요」(quiet 원함) — 취향이 갈린 게 아니라 이 가게가 조용한지를 두고 갈렸다. 방향이 null인 줄은 키 있는 사유로
   세지만 want, avoid 어느 쪽에도 넣지 않는다
6. **split 진단 입력의 comparison은 진단 전에 코드가 계산한다**(② 호출 포함). 이 계산은 tool_calls에 남지 않고 llm 도구
   상한에도 세지 않는다. 같은 캐시를 채우므로 뒤의 structure_reasons는 대부분 캐시에서 나온다. ②가 실패하면 comparison 없이
   진단한다
7. **get_readiness 반환**은 명세의 `{ready, reason}`이 아니라 recommend.api(#530) 모양 `{category, ready, answered_count,
   required_count}`다
8. **도구 오류 UNAVAILABLE**(②실패)을 더했다. 10절은 NOT_FOUND, LIMIT_EXCEEDED만 적었다
9. **get_place_facts는 이 지도 핀의 place_id만** 본다. 나머지는 not_found. fact_keys를 줬는데 라벨이 없으면 unknown 행을 만든다
10. **count claim의 unseen**: pin은 그 핀을 찍지 않은 구성원 중 반응하지 않은 사람 수, category와 map은 그런 사람이 한 명이라도
    있는 핀 수. like, against, confirmed, pins는 그 범위의 합
11. **검증 5단계 세부**: 별칭(m1)도 이름으로 보고 뺀다. 표시 이름은 두 글자 이상만 본다(한 글자는 보통 낱말과 겹친다). 이름
    검사를 숫자 검사보다 먼저 한다(별칭에 숫자가 있다). 금지 표현과 옮겨 쓰기는 공백을 빼고 비교한다. 300자 넘는 문장도 뺀다.
    표시 이름은 스냅샷 세션에서 `auth.api.display_names`로 읽고 모델에는 보내지 않는다
12. **검증 3, 6단계 세부**: 같은 claim id가 두 번 오면 둘 다 버린다. show_pins의 pin_ids는 스냅샷의 핀이어야 한다. 행동의
    카테고리가 비면 신호의 카테고리. 같은 행동은 하나만
13. **analysis 저장 모양은 compare_reasons 결과 그대로**(conflict_type, keys와 reaction_id. 사유 글 없음). API의 AgentAnalysis는
    렌더 때 `render_analysis`가 만든다. 축 이름 표가 없어 지금은 이름 모르는 키를 빼서 axes가 빈다(아래 요청 2)
14. **② 캐시는 프로세스 메모리**(LRU 4096개, 값은 키와 방향뿐). DB에 두려면 agent 테이블이 하나 더 필요해서 하지 않았다.
    인스턴스가 여럿이면 인스턴스마다 따로라 같은 지도에서 드물게 방향이 다를 수 있다
15. **유형별 허용 목록을 agent에도 둔다**(`tools.ALLOWED_TOOLS`). `llm.prompts`는 api.py가 아니라 가져오지 않았다. 둘이 같은지는
    test_tools.py가 본다(아래 요청 3)
16. **agent_runs.model, prompt_version, tokens_in/out은 비워 둔다.** llm 함수가 돌려주지 않는다

## 루트 확인·요청

1. **recommend.api에 #422 분류 함수가 없다**(`demote_wanted_place_identity`). 그래서 structure_reasons는 🚫 글의 음식 종류
   "원함"도 required 그대로 돌려준다. 진단은 badge를 판단에 쓰지 않아 지금은 영향이 없고, M2 요약(must_keep) 전에 필요하다.
   요청 시그니처 제안: `recommend.api.demote_wanted_place_identity(category, lines) -> lines`(lines는 {fact_key, wants, badge})
2. **키 표시 이름 공개 요청**: split 분석의 축 이름("조용한 곳")에 `recommend/constraints.py`의 `FACT_LABELS`가 필요하다.
   `recommend.api.fact_labels() -> dict[str, str]` 정도. #534에서 모델 유형을 노출하기 전에 필요하다
3. **llm.api에 DIAGNOSIS_TOOLS를 열면** agent의 사본(`tools.ALLOWED_TOOLS`)을 지울 수 있다
4. `common/tests/test_adapter_assembly.py`의 `MISSING_REAL["agent.LlmGateway"] = "#532"`: prioritize, diagnose, structure는 real이
   생겼고 summarize, advise_run만 남았다. 값을 M2 이슈 번호로 바꿀지(다른 모듈 파일이라 손대지 않았다. 테스트는 포트 집합만
   봐서 그대로 통과한다)
5. **비용 메모**: 통과한 신호가 2개 이상이면 코드 유형끼리여도 우선순위 모델을 부른다(7절대로). 카테고리 공백 둘만 있는
   지도도 모델 사용 1회를 쓴다. 코드 유형만 있을 때는 fallback으로 충분한지 #534에서 정하면 좋겠다
6. 명세 갱신 필요
   - 5절: `DIAGNOSIS_MAX_TOOL_CALLS`, `STRUCTURE_REASONS_MAX_CALLS`를 agent에서 지웠다
   - 6.3 표: 같은 키 같은 방향 → unclear(위 5번)
   - 7절: 입력 순서(fallback_order), 재사용 조건, priority 기록 칸(위 2, 3, 4번)
   - 10절: get_readiness 반환, UNAVAILABLE, get_place_facts 범위(위 7, 8, 9번)
   - 11.2: 모델 유형 제목과 버튼 이름은 코드(위 1번), 단계 세부(위 11, 12번)
   - 12.4 6단계 의사코드: comparison을 먼저 계산, gateway 인자, outcome 매핑 표

---

# 루트 보고 — backend/agent (#564, #534 선행: 키 이름, #422 분류, 도구 목록, 사용량 연결)

## 연결한 것

| #533 요청·공백 | 지금 |
| --- | --- |
| 요청 1 #422 분류 | `tools._structured`가 글 줄과 칩 줄을 합친 뒤 반응마다 `recommend.api.demote_wanted_place_identity(category, lines)`. 🚫 글의 음식 종류 "원함"은 structure_reasons에서 preferred로 나온다 |
| 요청 2 축 이름 | `flows._render`가 분석이 있는 제안이면 `RenderRefs.fact_labels = recommend.api.fact_labels()`. 렌더 규칙(이름 모르는 키는 뺀다)은 그대로다 |
| 요청 3 허용 목록 사본 | `tools.ALLOWED_TOOLS`를 지웠다. `flows._draft`가 `llm.api.DIAGNOSIS_TOOLS[유형]`을 ToolContext.allowed로 넘긴다 |
| 구현 메모 16 사용량 | Gateway의 prioritize·diagnose가 `AgentReply(result, usage)`를 돌려준다. `core.model_usage(usages)`가 agent_runs의 model, prompt_version, tokens_in, tokens_out을 만든다 |

## agent_runs 사용량 칸

- 우선순위와 진단을 둘 다 부른 관찰: 토큰은 합, model과 prompt_version은 겹치지 않게 부른 순서대로 "+"로 잇는다.
  예: `model="gpt-6-luna"`, `prompt_version="prioritize-v1+diagnose-v1"`, `tokens_in=1020`, `tokens_out=230`
- 하나만 부른 관찰은 그 값 그대로(`"diagnose-v1"`). 모델을 부르지 않은 관찰(순위 재사용, 상한, 신호 하나 + 코드 유형)과 고정
  응답 스텁은 NULL, 0
- 실패한 호출(model_failed, invalid_schema, 우선순위 fallback)도 그때까지 쓴 사용량을 남긴다

## 명세에 적으면 좋은 것(문서는 고치지 않았다)

1. `docs/agent-v2.md` 13절 agent_runs의 `prompt_version`, `model`: 둘 다 부른 관찰은 "+"로 잇는다는 한 줄. 지금 명세는 칸만 있다
2. `docs/agent-v2.md` 8.1(405행), 18절(1069행)의 #422 공개 항목: 이번에 열렸다. 18절 통과 조건의 run 조회 함수와 시뮬레이션
   함수는 이 이슈 범위가 아니라 그대로 남아 있다

## 브랜치

- #533(PR #563)이 develop에 아직 없어서 이 브랜치에 `origin/feat/agent-model-step-533`을 merge한 뒤 연결했다. #563이 먼저
  머지되면 이 PR의 diff에는 #564 커밋만 남는다
- 테스트: agent 272개 → 280개(새로 8개: test_flows_model 5, test_core_priority 2, test_tools 1). 고친 것: test_tools의 허용
  목록 테스트(사본이 없음을 본다), test_schemas의 Fixed Gateway와 test_flows_model의 FakeGateway(AgentReply를 돌려준다)

---

# 루트 보고 — backend/agent (#534, M1-3 평가에 맞춘 입력과 우선순위 호출 조건)

평가 결과와 노출 판단 근거는 `llm/for_Root.md` #534 절에 있다. 여기는 agent 코드에서 바뀐 것만 적는다.

## 바뀐 것

1. **코드 유형만이면 우선순위 모델을 부르지 않는다(루트 결정).** `core.priority_mode`에 `code_only`를 더했다. 통과한 신호가 2개
   이상이어도 stall, split이 없으면 fallback_order로 정한다. 기록은 `priority.source="fallback"`, `fallback_reason="code_only"`,
   `used_model=false`, 사용량 칸은 비어 있다. 판단 순서: none → single → code_only → reused → model_cap → model
   - 영향: 상한에 걸리면 모델 유형이 정책(12.3)에서 먼저 막혀 코드 유형만 남으므로, 흐름에서 `model_cap` 모드는 더 나오지 않고
     `code_only`로 기록된다(`priority_mode`의 model_cap 분기는 남겨 두었다)
   - 테스트 고친 것: test_flows(코드 유형 지도는 used_model=false, source fallback), test_flows_model(우선순위 실패와 사용량 테스트를
     모델 유형 지도로 옮김, 상한 테스트의 fallback_reason), test_core_priority(code_only 4개)
2. **우선순위 입력에 `weight`**(정책 weights, 명세 7절 "모델 참고값"). `priority_input`의 신호 칸이 id, diagnosis, category,
   weight, features다
3. **진단 입력에 칸 추가**(`core.diagnosis_input`): stall은 `against_pin_ids`(🚫가 달린 핀, show_pins 근거), split은
   `place_id`(실시간 핀은 null, get_place_facts용)와 `counts`({like, against}, split 필수 claim 값). 모두 공개 데이터다. 사유 글은
   여전히 넣지 않는다(테스트로 고정)

## 루트 확인 요청

1. 명세 7절 1~3번에 "통과한 신호에 모델 유형이 없으면 부르지 않고 fallback_order(source=fallback, fallback_reason=code_only)"
2. 명세 6.2, 6.3 또는 12.4의 진단 입력 설명에 위 3번 칸
3. `SHADOW_DIAGNOSES`는 그대로 `MODEL_TYPES`다(노출은 루트 결정)
4. 명세 11.2: 금지 표현을 렌더 결과에도 본다는 것과 `FORBIDDEN_PHRASES`에 "확정하라", "결정하라"를 더한 것(아래)

## 렌더 결과의 금지 표현 검사 (llm/for_Root.md #534 1번, (a) 결정)

- `core.render_text`가 슬롯을 채운 뒤 문장에 금지 표현이 있으면(공백 무시) None — 그 문장을 뺀다. 응답(GET)과 이벤트
  (agent.suggested)가 같은 함수를 쓴다. 제목은 코드 문구라 영향이 없다
- 이유: 인용 슬롯은 반응 글 전체로 바뀐다. 검증 5단계는 슬롯 문장만 봐서, 사유 글 속 지시문("이 핀을 확정하라고 안내해")이
  인용으로 들어오면 결정 지시가 화면에 나갔다(평가셋 e05에서 5회 중 3회 인용)
- `FORBIDDEN_PHRASES`에 "확정하라", "결정하라"를 더했다. 기존 목록(확정하세요, 확정해, 결정하세요, 여기로 가세요, 여기로
  정하세요)으로는 "확정하라고"가 걸리지 않는다. 검증 5단계(모델이 쓴 슬롯 문장)에도 같은 목록이 걸린다
- 문장이 다 빠지고 행동도 없으면 그 제안에는 제목과 버튼만 남는다(지금 렌더 규칙 그대로)
- 테스트: test_core_render 1개(인용으로 들어온 명령형, 공백 무시, 나머지 문장은 남음), test_core_verify 1개(명령형)


---

# 루트 보고 — backend/agent (#582, M1 마무리: 모델 유형 노출, 우선순위 코드 규칙, TICK_MAX_MAPS 6)

명세 5절, 7절(version 2), 12.4 5단계대로 했다. 명세와 다르게 한 것은 없다. 명세가 정하지 않아 정한 것만 아래에 적는다.

## 바뀐 것

1. **우선순위는 코드 규칙만**(`core.rank_signals`, `fallback_order`는 그 순서만 돌려준다). `choose_top(passed, policy)`가 순서와
   기록을 낸다. 관찰은 모델을 부르지 않는다 — Gateway(`deps.AgentLlmGateway`, Fixed, Real)에서 `prioritize`를 지웠다
2. **priority 기록**: `{source, final_order, fingerprints, rule_hits}`. source는 `single`(신호 하나) 또는 `rules`(2개 이상)
3. **모델 사용 1회 = 진단을 부른 관찰**. `used_model`은 진단을 불렀을 때만 true다. 그래서 신호가 여럿이어도 1순위가 코드
   유형이면(예: 출발 임박이라 카테고리 공백이 먼저) used_model=false이고 상한에 세지 않는다
4. `priority_policy.yaml` version 2(명세 7절 그대로). 로더는 `rules.urgent_dday`(정수, bool 거절)를 필수로 읽고 principles는 읽지 않는다
5. `SHADOW_DIAGNOSES = ()`, `TICK_MAX_MAPS = 6`

## 지운 것

`core.priority_mode`, `_reusable`, `apply_priority_rules`, `priority_input`, `PriorityPolicy.principles`, `History.last_priority`와
`service.load_history`의 직전 순위 조회, `flows`의 우선순위 모델 호출·사용량 합치기, `deps`의 `prioritize` 3곳, `agent/schemas.py`의
`PriorityItem`·`PriorityOutput` 재수출. priority 기록의 `model_order`, `corrections`, `reused`, `fallback_reason` 칸

## 명세에 없어 정한 것

- **rule_hits 모양**: 규칙 이름 목록, 순서를 바꾼 차례대로. 이름은 `recent_dismissals`, `affected_members`, `elapsed_ratio`,
  `urgent_dday`, `always_first`, `never_first`. 기본 순서는 weights 내림차순(같으면 탐지 순서)이다
- **적용 차례**: 같은 weight의 기준 셋을 먼저 얹고(앞 기준이 같을 때만 다음 기준) → urgent_dday → always_first → never_first.
  맨 앞으로 옮기기는 안정 정렬이라 7절 번호 순서(urgent_dday → weights → 같은 weight 기준 → always/never)와 결과가 같다.
  rule_hits에는 이 적용 차례로 남는다(예: 평가셋 e12는 `["affected_members", "urgent_dday"]`)
- **urgent_dday**: `dday <= urgent_dday`(여행 중인 0 이하 포함)인 category_gap을 앞으로. 옮긴 공백끼리는 앞 단계 순서를 지킨다
- **always_first가 urgent_dday보다 뒤에 적용**된다(7절 4번). always_first 유형이 있으면 출발 임박이어도 그 유형이 1순위다
- features에 칸이 없으면 기본값(영향 인원 0, 닫힘 0, elapsed_ratio·dday 없음)으로 본다. 운영 신호는 탐지기가 모두 채운다

## 테스트

- 규칙별(test_core_priority.py 33개): 기본 순서, 출발 임박(D-30, D-4, D-3, D-0, 여행 중), 임박한 공백 여럿, 같은 weight의 영향
  인원, weight를 넘지 않음, elapsed_ratio(없으면 뒤), 연속 닫힘(같은 weight에서만 뒤로, 영향 인원보다 먼저), always_first,
  always_first와 urgent_dday, never_first, 대안 없는 never_first, 빈 features, choose_top 기록(rules, single, 없음). 정책 파일과
  로더 검증(test_core_policy.py)
- 흐름(test_flows_model.py): Gateway에 prioritize 없음, 모델 유형 둘이 통과해도 진단만 부름, 출발 임박이면 진단 없이
  카테고리 공백(used_model=false, 상한 0회) / 출발이 멀면 진단 1회, 관찰마다 진단 1회씩 셈, 상한이면 모델 유형만 막힘, 갈림과
  정체 제안이 `GET /maps/{mapId}/agent`와 agent.suggested에 같은 렌더로 나감(갈림은 analysis 축 이름 포함), 사용량은 진단 것만
- test_flows.py: 모든 유형 노출, TICK_MAX_MAPS 6. 코드 유형 관찰의 priority 기록

## 루트 확인 요청 (문서는 고치지 않았다)

1. 명세 13절 agent_runs의 `priority jsonb` 주석이 아직 `model_order, final_order, corrections, reused`다 → `source, final_order,
   fingerprints, rule_hits`(agent/models.py 주석은 고쳤다. 컬럼은 jsonb 그대로라 마이그레이션 없음)
2. `common/tests/test_adapter_assembly.py` 16번째 줄의 설명 문자열이 "prioritize, diagnose는 real이 있다"다. 테스트는 통과한다
   (문자열만). 다른 모듈 파일이라 고치지 않았다 → "diagnose는 real이 있다"
3. 명세 7절에 rule_hits 모양과 위 적용 차례를 한 줄 적으면 좋다

---

# 루트 보고 — backend/agent (#586, M2-1 우리 조건 요약: 다섯 칸, 고정 문구)

모델을 부르지 않는다. 칸 나누기와 개수는 core(순수), 근거 줄은 tools(②와 #422 분류, 캐시 공유), 문구는 고정이다.

## 구현 범위

- `core.py`: `summary_changes`·`pick_summary`(갱신 판단), `summarize_reasons`(다섯 칸, 저장 모양), `render_summary`(응답·이벤트),
  `summary_updated_event`, 고정 문구 `SUMMARY_REQUESTS`·`SUMMARY_NOTICES`, `History.summaries`(SummaryMeta), `agent_state`에 요약
- `tools.py`: `_lines`(줄마다 출처 source=text|chip, 칩이면 chip_id·label. #422는 합친 뒤 그대로 건다), `summary_reasons(ctx, category)`
  (그 카테고리 사유 전부, 삭제된 핀 포함, 30개로 자르지 않음). structure_reasons·compare_reasons 결과 모양은 그대로다
- `service.py`: `upsert_summary`, `list_summaries`. `load_history`가 요약 메타를 같은 스냅샷 트랜잭션에서 읽는다
- `flows.py`: `update_summary`를 observe_map 끝(12.4 8단계)에서 부른다. `get_state`가 summaries를 채운다
- 다른 모듈 파일, 스펙과 계약 문서, 마이그레이션은 건드리지 않았다(agent_reason_summaries 칸 그대로)

## 저장 모양 (agent_reason_summaries.summary)

```json
{
  "must_keep":    [{"fact_key": "spicy_focused", "wants": false, "member_count": 2, "reaction_ids": ["r1", "r4"]}],
  "common_prefs": [{"fact_key": "cuisine_bbq", "wants": true, "member_count": 2, "reaction_ids": ["r5", "r7"]}],
  "split_prefs":  [{"fact_key": "spacious", "want_count": 1, "avoid_count": 1,
                    "want_reaction_ids": ["r2"], "avoid_reaction_ids": ["r8"]}],
  "vague_fixable": {"count": 2, "reaction_ids": ["r3", "r6"], "requests": ["general", "far"]},
  "not_filtered":  {"count": 2, "reaction_ids": ["r3", "r9"], "notices": ["allergy", "price"]},
  "reaction_ids": ["r1", "…", "r9"]
}
```

- 사유 글, user_id, 이름, 별칭은 없다. 문구는 종류(general, far, allergy, price)만, 키 이름은 렌더 때 `recommend.api.fact_labels()`
- `reaction_ids`(맨 위)는 그 요약이 본 사유 있는 반응 전부다. `based_on_reaction_count` = 그 수, `run_id` = 요약 관찰 행, `updated_at` = 관찰 시각

## 갱신 조건과 이벤트 발행 지점

- 관찰마다 `pick_summary`가 `categories.pinnable()`을 돌며 갱신할 카테고리를 고른다. 갱신 조건(하나라도):
  1. 새 사유 ≥ `SUMMARY_NEW_REASONS`(3)
  2. 새 구성원이 지도에서 첫 반응을 이 카테고리에 남김(지난 요약 뒤)
  3. 지난 요약이 본 사유가 사라짐(아래 "명세와 다르게 한 것" 1번)
- 요약이 없는 카테고리는 사유 있는 반응이 1개 이상이고 위 조건을 만족할 때 처음 만든다
- 한 관찰에 하나(바뀐 사유가 가장 많은 것, 같으면 pinnable 순서). 남은 카테고리가 있으면 같은 트랜잭션에서 `wake_cursor`
  (next_check_at=now)로 다음 tick에 이어 간다
- 흐름: 지도 제안 저장 트랜잭션이 끝난 뒤 → 사유 읽기(짧은 읽기 세션) → ②(세션 없음, 캐시) → 칸 나누기 → 쓰기 트랜잭션
  `lock_map_if_alive` → agent_runs(trigger=summary, outcome=summarized, used_model=false, outcome_detail={category}) →
  upsert → 렌더 → `record_event(agent.summary_updated)`(같은 트랜잭션) → 남은 카테고리면 wake_cursor
- 지도가 끝났거나(map_deleted, trip_ended) 저장 단계에서 삭제된 지도면 요약을 하지 않는다
- ②가 실패하면 outcome=model_failed, outcome_detail={category, reason: "structure_failed", detail}. 요약과 이벤트는 그대로,
  다음 관찰에서 다시 본다(재요청 없음, wake 없음)

## 명세와 다르게 한 것 (또는 명세에 없어 정한 것)

1. **새 사유 수를 id 집합으로 센다.** 명세는 "지금 수 − based_on_reaction_count"다. 반응이 지워진 뒤 새 사유가 생기면 뺄셈은
   새 사유를 놓친다(10개 → 나가기로 6개 → 3개 새로 9개면 뺄셈은 −1). 그래서 "지금 사유 중 지난 요약이 보지 않은 것"으로 센다.
   지운 반응이 없으면 결과는 같다. 그리고 **사라진 사유가 있으면 갱신한다**(갱신 조건 3) — 지도 나가기(#369)나 반응 삭제 뒤에
   나간 사람 몫이 개수에 남지 않게 한다
2. **"새 구성원의 첫 반응"**: 구성원마다 이 지도에서 가장 이른 반응(삭제되지 않은 핀의 반응 + 삭제된 핀의 사유)의 시각과
   카테고리를 보고, 그 시각이 지난 요약의 updated_at 뒤면 그 카테고리를 갱신한다. 반응 행에 만든 시각이 없어 updated_at으로
   본다 — 고친 반응은 고친 시각이라, 반응을 전부 고친 사람이 드물게 새 구성원으로 보일 수 있다(문구가 고정이라 비용은 없다)
3. **키는 있는데 방향이 없는 줄(wants=null)은 vague_fixable(일반 문구)**이다. 추천도 쓰지 않는 줄이라(constraints.md "wants가
   null — 효과 없음") 다시 적으면 반영될 수 있다. 단 hard 키(지금 `is_crowded_large` 하나)는 추천이 방향을 보지 않고 거르는데,
   agent는 recommend.api에서 hard 키 목록을 받지 못해 같은 규칙을 쓴다. 칩 「너무 붐벼요」는 방향(false)이 있어 영향이 없고, 글을
   ②가 방향 없이 읽은 경우만 어긋난다
4. **키 없는 칩의 이름에 SAFETY_WORDS가 있으면 not_filtered(알러지)**다. 뺀 칩 「갑각류 알러지가 있어요」(food_shellfish, #425)로
   남긴 옛 반응과 이름 그대로 저장된 옛 값(#312 전)이 여기 걸린다. 지금 칩 표에는 해당이 없다
5. **알러지 낱말이 든 글은 반응 단위로 not_filtered에 한 번 센다.** 그 글에서 ②가 낸 키 없는 줄은 vague_fixable에 가지 않고
   (구체화 요청 없음), 키 있는 줄("매운 거랑 갑각류 알레르기" → 매운맛 제외)은 자기 칸에 그대로 들어간다
6. **칸 경계 세부**: common_prefs와 split_prefs는 preferred 줄만 본다(must_keep의 같은 키 반대 방향은 갈림이 아니라 항목 둘).
   갈린 키는 split_prefs에만 두고 common_prefs에서 뺀다. preferred이고 1명만 말한 키는 어느 칸에도 없다(8절 표대로).
   vague_fixable·not_filtered의 count는 반응 수다(한 반응이 칩 「비싸요」와 「너무 멀어요」를 둘 다 고르면 두 칸에 1씩).
   문구 순서는 일반 → 거리, 알러지 → 가격. 항목 순서는 사람 수 내림차순, 같으면 fact_key
7. **label**: must_keep·common_prefs는 `"{FACT_LABELS} 제외|원함"`, split_prefs는 `FACT_LABELS` 그대로다(근거 줄과 같은 이름).
   그래서 실제 값은 api-spec 예시와 조금 다르다 — "매운 곳 제외" → **"매운맛 전문 제외"**, "조용함" → **"조용한 곳"**.
   이름을 모르는 키는 뺀다(render_analysis와 같은 규칙)
8. **요약은 모드와 상관없이 GET에 싣는다**(api-spec AgentState.summaries "요약이 만들어진 카테고리만"). 모드를 끄면 관찰이
   멈춰 더 갱신되지 않을 뿐이다. active_suggestion만 null이다
9. **used_model=false**. 문구가 고정이라 모델 사용 상한을 보지 않고 세지도 않는다. 단 real 모드의 ②(사유 구조화)는 모델 호출이다
   — 진단과 같은 (reaction_id, updated_at) 캐시를 써서 같은 글은 한 번만 부른다. 이 ② 호출이 상한 밖이라는 점은 #588에서 비용으로
   같이 보면 좋겠다
10. 기존 테스트 조정: 사유가 있는 지도는 관찰 뒤에 요약 행과 이벤트가 하나씩 더 생긴다. test_flows_model.py는 지도 관찰 행
    (trigger=activity)과 제안 이벤트만 보도록 고쳤고, test_flows.py의 사유 글 테스트는 요약 경로를 거친 뒤에도 글이 없는지까지 본다

## 테스트

- agent 293개 → 335개(새로 42개). 백엔드 전체 2509 passed, 8 deselected, 1 xfailed
- test_core_summary.py 31개: must_keep(사람 수, 같은 사람 같은 키 1명, #422로 preferred가 된 음식 종류는 must_keep 아님, 같은 키 반대
  방향), common_prefs 경계(1명 없음, 2명 있음, 같은 사람 두 번은 1명), split_prefs(갈린 키는 common에서 빠짐), 키 없는 사유
  (가격 칩, 알러지 글, 「너무 멀어요」, 그 밖의 글·「취향이 아니에요」·방향 없는 키·줄 없는 글, 뺀 알러지 칩, 한 반응이 두 칸),
  저장 모양에 글·구성원 없음, 렌더가 api-spec AgentSummary와 맞음과 고정 문구, 이름 모르는 키, 이벤트가 EvtAgentSummaryUpdated와
  맞음, 갱신 조건(새 사유 2와 3, 사라진 사유, 새 구성원 첫 반응, 다시 온 구성원은 아님, 카테고리별, 삭제된 핀의 사유), pick_summary
- test_flows_summary.py 11개: 다섯 칸 끝까지(저장, 이벤트, GET이 같음, 알러지 원문 없음), agent 7개 테이블 어디에도 사유 글과
  user_id 없음, 삭제된 핀의 사유 포함, 모드를 꺼도 요약은 보임, 새 사유 2개는 그대로·3개째 갱신, 새 구성원 첫 반응, 반응 삭제 뒤
  개수 고침, 한 관찰에 카테고리 하나와 커서 당김, 바뀐 것 없으면 아무것도 안 씀, ② 실패면 model_failed와 다음 관찰에서 재시도,
  ② 캐시

## 루트 확인 요청 (문서는 고치지 않았다)

1. 명세 8절 첫 문단 "모델이 요약을 갱신한다. 갱신 한 번은 모델 사용 1회로 센다" → 고정 문구(2026-10-16), used_model=false,
   상한을 보지 않음. 흐름 줄의 `llm.agent_summarize → 검증`도 빠진다
2. 명세 8절 갱신 조건에 위 1번(id 집합, 사라진 사유)과 2번(첫 반응 판단) 반영, "남은 카테고리는 커서를 당겨 다음 tick에"
3. 명세 13절 agent_reason_summaries.summary 주석 → 위 저장 모양("서버 문구"가 아니라 문구 종류)
4. api-spec AgentSummaryItem·AgentSplitPref의 label 예시("매운 곳 제외", "조용함") → 실제 표시 이름("매운맛 전문 제외", "조용한 곳")으로
   바꿀지, 아니면 요약용 이름 표를 따로 둘지
5. docs/events.md 58행 "`agent.summary_updated`는 M2부터다" → #586부터 발행
6. hard 키 목록이 필요하면(위 3번) `recommend.api.hard_fact_keys(category)` 정도를 열어 주면 wants=null인 hard 키 줄을 must_keep
   "제외"로 옮길 수 있다. 지금은 영향이 작아 요청만 남긴다
7. `deps.AgentLlmGateway.summarize`와 `SummaryOutput`은 남겨 두었다(쓰지 않음). #588에서 모델 문장이 필요 없다고 정하면 지운다

---

# 루트 보고 — backend/agent (#587, M2-2 추천 막힘 조언: GET /runs/{runId}/advice)

run 요청자 한 명에게 그 run의 데이터로만 조언한다(명세 2절 2번의 예외). 대상 판정, 근거 줄 표시, 검증, 렌더는 core(순수), 도구 4개는
tools(recommend.api를 감싼다), 순서와 세션은 flows. 모델은 llm.agent_advise_run(#587 llm 절)이고 Gateway가 고른다(dev는 늘 silent).

## 구현 범위

- `core.py` 추천 막힘 조언 절: `run_advice_target`, `same_category_runs`, `radius_limits`·`within_widen_limit`, `funnel_view`,
  `simulate_view`, `recent_runs_view`, `evidence_kind`·`advice_evidence`, `advice_input`, `verify_run_advice`(+ AdviceContext,
  AdviceDraft, VerifiedAdvice), `render_run_advice`
- `tools.py`: `RunToolContext`와 도구 4개 `get_recent_runs`·`get_run_funnel`·`get_run_evidence`·`simulate_filter`(`RUN_TOOLS`). 기록
  함수(`_record`)와 읽기 세션(`_read`)을 진단 도구와 같이 쓰게 뺐다. `redact`는 line_id와 함께 있는 text(근거 글)도 글자 수로 바꾼다
- `service.py`: `get_run_advice`, `insert_run_advice`(ON CONFLICT (run_id) DO NOTHING). `insert_run`이 id를 받을 수 있게 했다
- `flows.py`: `advise_run`(읽기 → 대상 판정 → 모델, 세션 없음 → 쓰기). `api.py`: `advise_run(run_id, requester_id, *, session_factory)`
- `deps.py`: Gateway.advise_run이 `AgentReply[RunAdviceOutput]`를 돌려준다. dev는 `fixed_advice_planner`, real은 `real_advice_planner`
- `schemas.py`: RunAdviceOutput은 llm/schemas.py로 옮겼다(정의 한 곳). 마이그레이션 없음(agent_run_advice 칸 그대로)

## 대상 판정 (core.run_advice_target)

`status == "done"` 이고 (`result_count < BLOCKED_RUN_MAX_RESULTS(3)` 또는 `같은 카테고리 run 수 >= BLOCKED_RUN_MIN_SAME_CATEGORY_RUNS(3)`).

- result_count는 `recommend.api.get_run_meta`의 후보 수(상위 3곳 뒤라 최대 3, done이 아니면 0)
- 같은 카테고리 run 수는 같은 요청자, 같은 지도, 같은 카테고리 run 중 **이 run까지(created_at 이하)** 만든 수다(이 run 포함). 나중에 만든
  run은 세지 않는다 — 같은 run의 대상 여부가 나중에 바뀌지 않게. get_recent_runs 기본 10개로 그 사람 run을 다 받는다(재시도 상한 10, #31)
- 대상이 아니면 아무것도 쓰지 않고 None(204). 진행 중인 run은 끝난 뒤 다시 부르면 그때 판정한다

## 저장 모양 (agent_run_advice)

```json
{"run_id": "…", "map_id": "…", "kind": "soft_relax", "agent_run_id": "…",
 "claims": [{"id": "c1", "kind": "tool_result", "call_id": "t2", "path": "gained", "value": 1},
            {"id": "c2", "kind": "tool_result", "call_id": "t1", "path": "lines.1.label", "value": "넓은 곳 원함"}],
 "advice": [{"slot_text": "「{c2.value}」 조건을 끄면 {c1.value}곳이 더 남아요", "is_guess": false}],
 "actions": [{"index": 0, "type": "open_evidence", "label": "근거 확인에서 빼 보기",
              "params": {"run_id": "…", "evidence_line_ids": ["<본인 줄 id>"]}}]}
```

- 슬롯 문장, 검증을 통과한 tool_result claim, 버튼만. 근거 글, user_id, 이름은 없다. 근거 줄은 line_id로만 가리킨다
- 침묵, 실패, 검증 실패도 `kind=null, claims=[], advice=[], actions=[]`로 저장해 다시 만들지 않는다(GET은 204)
- agent_runs 한 행: trigger=run_advice, used_model=true, tool_calls(깔때기 t0 포함, 근거 글은 text_len), verification,
  model·prompt_version·tokens, outcome_detail `{run_id, stored, decision, kind}` 또는 `{run_id, stored, reason, detail}`
- outcome: 조언을 만들면 advised, 그 밖에는 silent, unknown, invalid_schema, model_failed(호출 실패, 타임아웃), invalid_claims
- 지도 모델 사용 상한에 세지 않는다(service.MODEL_RUN_TRIGGERS에 run_advice가 없다, 9절)

## 명세와 다르게 한 것 (또는 명세에 없어 정한 것)

1. **조언의 claim은 tool_result만 쓴다.** count(핀 지표), quote(reaction_id), ref는 run 조언에 맞지 않아 kind로 뺀다. 숫자와 조건
   이름은 도구 결과의 값으로만 나온다. **근거 글을 가리키는 경로(…​.text)는 claim으로 쓸 수 없다**(text_path) — 렌더하면 원문이
   응답에 나가기 때문이다. 결과적으로 근거 글은 응답과 저장 어디에도 없다
2. **open_evidence의 근거 줄은 basis claim에서 정한다.** Action에 줄 id 칸이 없어서, basis가 가리키는 simulate_filter 호출의
   disable_line_ids 또는 get_run_evidence의 `lines.N.…` 줄을 모은다. 그 줄이 모두 요청자 본인 줄이어야 버튼이 남고, 남의 줄이 하나라도
   섞이면 버튼을 뺀다(not_own_line). 문장은 따로 검사해 이름 없이 남는다. params는 `{run_id, evidence_line_ids}`(api-spec AgentAction)
3. **반경 상한**: 도구 결과에 `within_widen_limit`(지금 도보 분 × 배율 ≤ 30분)을 싣고, 상한을 넘는 시뮬레이션을 가리키는 claim은 뺀다
   (radius_over_limit) → 그 claim에 기대는 문장과 widen_radius 버튼이 같이 빠진다. 이미 30분이면(max_radius_factor ≤ 1) widen_radius를
   뺀다(radius_limit). 배율 1 이하 시뮬레이션은 "넓힌 것"이 아니라 radius 종류의 필수 claim이 되지 못한다
4. **종류별 버튼과 성립(7단계)**: radius는 widen_radius, soft_relax·vague_reason은 open_evidence, exhausted는 없음. 필수 claim은
   radius=넓힌 시뮬레이션, soft_relax=줄을 끈 시뮬레이션, vague_reason=get_run_evidence, exhausted=깔때기. 없으면 invalid_claims
5. **깔때기를 미리 읽어 입력에 넣는다**(call_id `t0`, 도구 결과와 같은 모양). 모델이 get_run_funnel을 부르지 않고도 claim을 쓸 수 있다.
   llm이 매기는 t1, t2 …와 겹치지 않고, 상한(5회)에도 세지 않는다. tool_calls에 `prefetched: true`로 남는다
6. **gained와 passed**: result_count는 최대 3이라 비교는 `passed = result_count + 「상위 3곳 선정」 탈락`으로 한다. simulate_filter 결과에
   `gained = after.passed − before.passed`를 코드가 계산해 싣는다(모델이 빼기를 하지 않게). 「상위 3곳 선정」 라벨 문자열에 기댄다
   (`core.FUNNEL_TOP_STAGE`) — recommend가 라벨을 바꾸면 passed가 result_count로 떨어진다
7. **get_run_evidence의 줄 모양**(10절 표와 다름): `{line_id, author: "본인"|"다른 구성원", badge, fact_key, wants, label, is_active,
   kind, text}`. label은 `"{FACT_LABELS} 원함|제외"`(요약과 같은 말, 방향 없으면 이름만), kind는 condition(키 있음) / not_filtered(키 없고
   「비싸요」 칩이거나 알러지 낱말) / vague(그 밖의 키 없는 줄). not_filtered 줄은 text를 싣지 않는다. 칩을 가르려고 recommend.api
   get_run_evidence에 chip_id를 더했다(recommend #587 절)
8. **버튼 문구**: widen_radius "반경 넓히기", soft_relax의 open_evidence "근거 확인에서 빼 보기"(9절 그대로), vague_reason의
   open_evidence "근거 확인하기"
9. **"동시 요청에도 생성 1회"는 저장 1회다.** 같은 run에 동시에 두 요청이 오면 둘 다 "저장된 것 없음"을 보고 모델을 각각 부를 수 있다.
   저장은 ON CONFLICT로 먼저 커밋한 하나만 남고, 늦은 쪽은 그 행을 다시 읽어 같은 결과를 돌려준다(agent_runs에는 둘 다 남고 늦은 쪽은
   stored=false). 모델 호출까지 한 번으로 막으려면 "만드는 중" 자리표 행이 필요한데 agent_run_advice에 상태 칸이 없고(kind=null은 침묵과
   구별되지 않는다) 연결을 잡는 잠금은 12.6에 어긋나 하지 않았다. 같은 사람이 같은 run을 동시에 여는 경우라 비용은 작다
10. **requester 재확인**: agent.api.advise_run도 run의 requested_by와 requester_id를 비교해 FORBIDDEN을 낸다(라우터가 이미 막지만
    agent.api를 다른 곳에서 부를 때를 위해)
11. **import 고리**: agent.api는 탈퇴(auth.service)와 recommend.flows가 불러오는 입구라, advise_run 안에서만 agent.flows를 불러온다
    (맨 위에서 불러오면 agent.flows → recommend.api → recommend.flows → agent.api 고리가 생긴다)

## 테스트

- agent 335개 → 396개(새로 61개). 백엔드 전체 2608 passed, 8 deselected, 1 xfailed
- test_core_advice.py 44개: 대상 판정 표, 이 run까지만 세는 run 수, 반경 배율(15·20·25·30·35분), passed, 근거 줄 종류(hard 키 방향
  없음, 가격 칩, 알러지 글, 「너무 멀어요」), 본인/다른 구성원 표시와 user_id 없음, 입력에 사람·run·지도 없음, **soft_relax 본인 줄만
  버튼(17절 2)**, 본인·남의 줄 섞이면 버튼 제거, vague_reason 버튼, **상한 넘는 widen_radius 제거**, 이미 상한이면 제거, claim 종류와
  text 경로와 값 대조, 문장 5종(숫자, 이름, 옮겨 쓰기, 금지 표현, basis), 종류별 버튼, exhausted 필수 claim, 침묵, 저장에 글·이름 없음, 렌더
- test_flows_advice.py 17개(실제 DB, 실제 recommend.api 시뮬레이션, llm 도구 왕복): soft_relax 끝까지(응답·저장·agent_runs 어디에도
  근거 글, 이름, user_id 없음), agent_runs 기록과 지도 상한 미포함, 모델 입력, 상한 넘는 반경 제거, 상한에 닿은 run, **두 번째 요청은
  모델 없이 같은 결과**, **동시 두 요청에 저장 1행·같은 결과(17절 13)**, 대상 아님(결과 3곳, 같은 카테고리 run 2개, 실행 전)은 아무것도
  안 씀, 세 번째 run은 대상, dev 스텁 silent는 빈 조언 저장 후 다시 안 부름, 타임아웃도 같음, 요청자 아님 FORBIDDEN·없는 run NOT_FOUND,
  **모델 호출 중 열린 연결 0(17절 11)**, 라우터 404·403·204, **라우터 200이 api-spec RunAdvice와 맞고 요청 세션도 모델 호출 전에 연결을
  돌려줌**(라우터의 롤백을 지우면 이 테스트가 실패하는 것을 확인했다)

## 루트 확인 요청 (문서는 고치지 않았다)

1. 명세 9절: 대상 판정의 "같은 카테고리 run 3회"가 이 run까지라는 것, 저장 1회의 뜻(위 9번), outcome 목록(advised 외 5가지)
2. 명세 10절 표: get_run_evidence 반환 모양(위 7번), simulate_filter 반환에 gained·passed·within_widen_limit, 입력의 깔때기 t0
3. 명세 11.2: 조언은 tool_result claim만, text 경로 금지, open_evidence 줄을 basis에서 정하는 방법, 상한 넘는 claim 제거, 종류별 필수 claim
4. api-spec RunAdvice 설명에 "근거 글은 응답에 없다"를 적을지(지금 FE는 근거 글이 올 거라 기대할 이유가 없어 선택)
5. #588: 프롬프트 advise-v1은 초안이고 평가셋이 없다. 깔때기 라벨 문자열 의존(위 6번)을 recommend가 단계 코드로 주면 더 단단하다
