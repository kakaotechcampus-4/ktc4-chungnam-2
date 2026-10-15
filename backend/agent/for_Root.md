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
