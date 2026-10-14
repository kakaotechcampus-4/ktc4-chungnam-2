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
