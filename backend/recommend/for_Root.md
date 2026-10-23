# 루트 리뷰 가이드 — backend/recommend

`backend/pins/for_Root.md`·`backend/authz/for_Root.md`와 같은 형식. 이 파일은 네 세션에 걸친
작업을 누적해서 담는다 — 아래 "#707" 절이 최신, 그 아래 "#617" 절, 그 아래 "#587" 절, 그 아래 "#585" 절, "#569" 절, 그 아래 "#469" 절, 그 아래 "#190" 절, 그 아래 "#119·#114" 절, 그 아래 "#158·#146·#112 후속" 절, 그 아래 "#112" 절, 그 아래 "#124" 절, "#108" 절이 코어 파이프라인
전체, 가장 아래 "PR #71" 절이 `publish_candidate` 하나만 다룬 첫 세션 기록이다.

---

# #707 — 「+」 직접 추가는 선호, 요청당 5줄·run당 10개 상한 (멘토 리뷰 #680)

## 바뀐 것

- `service.add_manual_evidence`의 배지가 `reference` → `preferred`. ②에 보내는 입력 배지도 `preferred`다(프롬프트는 배지를
  특별히 다루지 않는다). 선호 집계(`flows` 안 `preferred_authors`·`avoided_authors`)는 source를 보지 않고 badge·fact_key·wants만
  보므로 코드 변경 없이 점수에 들어간다. ②가 키나 방향을 못 붙인 줄은 지금처럼 남고 효과가 없다.
- 한 요청 5줄: `schemas.EvidencePatchRequest.add`에 `max_length=5` → 422 `VALIDATION_ERROR`.
- run 하나 10개: `core.MANUAL_EVIDENCE_LIMIT = 10`, 넘으면 `AppError("EVIDENCE_LIMIT", detail={"limit": 10, "used": 이 요청 전 수})`.
  ×로 뺀 줄도 센다. 사람이 아니라 run 단위다(다른 구성원이 넣은 것도 합산).
- 검사는 두 번: 모델 앞 읽기 단계에서 한 번(넘으면 ②를 부르지 않는다), 모델 뒤 쓰기 단계에서 `service.lock_run`(run 행
  `FOR UPDATE`)으로 잠근 뒤 다시 한 번. 읽기 단계 잠금은 #275 롤백으로 풀려서 동시 요청을 못 막기 때문이다. 동시 요청이
  둘 다 앞 검사를 통과하면 늦은 쪽은 모델을 부른 뒤 409로 끝나고 줄은 남지 않는다.

## 루트 확인 필요 — "10줄"을 무엇으로 세나

**줄(행)이 아니라 「+」로 넣은 글 수로 센다**(`service.count_manual_entries`: source='manual' 행을 `(text, created_at)`으로 묶어
센다. created_at은 트랜잭션 시작 시각이라 한 요청에서 넣은 줄은 같다). 글 하나에 조건이 여럿이면 행이 여럿이 되는데(#419),
모델 앞에서는 글이 몇 행이 될지 모르고, 행으로 세면 "8개 넣었는데 막힌다"·`used`가 10을 넘는 응답이 생긴다. 상한의 목적(모델
입력 수)과 FE 문구("직접 추가는 10개까지예요")에 맞춰 **글 수로 정했다**(2026-10-24 사용자 확인).

- 한 요청 안의 같은 글은 `patch_evidence`가 ②를 부르기 전에 하나로 줄인다(`dict.fromkeys`, 순서 유지). 같은 글 5개를 보내 1개로
  세이면서 ②에는 5개를 넣는 우회를 막는다. 다른 요청에서 같은 글을 다시 넣으면 따로 센다.
- 남은 전제: created_at이 트랜잭션 시각이라는 것. 깨지면(행마다 다른 시각) 행 수로 세는 것과 같아져 더 엄격해질 뿐 상한이
  뚫리지는 않는다.
- **루트 몫**: `docs/constraints.md`·`docs/errors.md`·api-spec·CHANGELOG의 "run 하나에 10줄"을 "10개(글)"로 고친다. FE가 응답
  줄 수로 세면 서버보다 먼저 「+」를 끈다(아래 FE 참고).

## FE 참고

`EvidenceLine` 응답에는 source가 없어 FE가 직접 추가한 개수를 응답만으로 셀 수 없다. 「+」 끄기는 FE가 넣은 수를 세거나
409를 받고 끄는 방식이 된다. 직접 추가한 줄은 이제 `badge: preferred`라 "가능하면 맞춰주세요" 구역에 보인다
(`frontend/src/features/recommend/model.ts:44`의 reference 구역은 v1에서 비게 된다).

## 바뀐 테스트

- 기대값만 새 규칙으로: `test_service.py::test_add_manual_evidence_is_preferred`,
  `test_flows.py::test_patch_evidence_add_creates_manual_preferred_line`, `::test_plus_manual_line_goes_through_plan_evidence_and_is_preferred`,
  `::test_plus_manual_text_with_several_conditions_adds_a_preferred_line_per_condition`
- 새 테스트(`test_flows.py` "「+」 직접 추가는 선호, 상한" 절, `test_router.py`): "회 좋아해" → 횟집 1위·실격 0, 키·방향 없는 줄은 순위
  불변, 11번째 409(detail, 모델 안 부름), 뺀 줄도 셈, 조건 여럿인 글은 하나로 셈, 토글만인 요청·반응 줄은 세지 않음, 동시 요청
  (test_engine 두 세션), 같은 글 반복은 ②에 한 번, 라우터 6줄 422·11번째 409.
- 점수: 「+」 선호 작성자는 지지 1명이지만 직접 쓴 선호라 `WRITTEN_PREFERENCE_POINTS`(3점)다(#414). 테스트는 점수 값이 아니라
  순위로 확인한다(후보에 score 컬럼이 없다).

---

# #617 — 반대 칩의 "원함"은 선호로 (접근성 칩 제외)

## 바뀐 규칙

`core.demote_wanted_place_identity`(이름·시그니처 그대로, agent는 `recommend.api`의 같은 이름으로 부른다)가 required이면서
wants=true인 줄 중 아래를 preferred로 내린다.

- 글 줄(chip_id 없음): 키가 가게의 정체(음식점 cuisine_*)일 때만 — #422 그대로. "주차 돼야 해요"는 required
- 칩 줄(chip_id 있음): 전부 — food_wait, food_cramped, cafe_noisy, cafe_seat, sight_noisy. 예외는 `core.REQUIRED_WANTED_CHIP_IDS`
  (= {"sight_inaccessible"})
- wants=false 줄(「매워요」 등), 다른 배지, 키 없는 칩(wants가 null)은 그대로

docstring은 constraints.md 절 이름을 "🚫 사유 안의 원함은 선호다"(#422, #617)로 적었다. **지금 constraints.md는 아직 옛 이름
("음식 종류 '원함'")이고, 그 절 표에 칩 「좁아요」 → required(그대로) 줄과 "「좁아요」처럼 🚫 안의 원함이 필요 조건인 경우도 있어서"
문장이 남아 있다.** 칩 절의 배지 설명("배지는 required")도 루트 몫이다.

## recommend 밖에서 기대값만 고친 테스트 (같은 PR, 커밋은 모듈별)

옛 규칙(칩 원함 = required)을 단언하던 4개. 모두 원함 칩이 preferred가 된 것 때문이었고, agent·integration 운영 코드는 그대로다.
요약 테스트는 한 사람만 남긴 칩이라 「좁아요」가 must_keep에서 빠져도 common_prefs(2명 이상, agent-v2.md 요약 칸 표)에는 들지 않는다 —
선호 칸에 보이려면 같은 칩을 두 명이 남겨야 한다.

| 테스트 | 옛 단언 | 새 기대값 |
|---|---|---|
| `integration/test_reason_chips_412.py::test_chips_and_text_become_one_line_each_and_only_text_goes_to_the_planner` (61행) | 세 줄 모두 badge required | 「좁아요」 줄만 preferred |
| `agent/tests/test_tools.py::test_structure_reasons_uses_planner_for_text_and_chip_table_for_chips` (164행) | spacious 칩 줄 required | preferred |
| `agent/tests/test_flows_summary.py::test_two_new_reasons_wait_and_third_updates` (252행) | must_keep 4개 | must_keep은 매워요·느끼해요 2개, common_prefs 빈 칸(「웨이팅이 길어요」·「좁아요」가 빠진다) |
| `agent/tests/test_flows_summary.py::test_one_category_per_observation_and_cursor_pulled_for_the_rest` (303행) | 카페 must_keep[0]이 quiet(칩 「시끄러워요」) | 카페 요약이 반응 1개를 보고 must_keep·common_prefs가 둘 다 빈 칸 |

## recommend 안에서 바뀐 테스트

- `test_flows.py`: `test_create_run_turns_each_chip_into_its_own_evidence_line_without_calling_the_model`(「좁아요」 badge
  preferred), `test_soft_chip_becomes_a_directed_requirement` → `..._only_when_it_avoids`(실격 조건은 spicy_focused만)
- `test_core.py`: 그대로 두는 줄 목록의 spacious 줄 주석을 "글"로 고쳤다(칩이 아니라 그대로 required)
- 추가: 「좁아요」만 있는 run(좁은 곳 실격 0, 넓은 곳이 rank 1 — 좁은 곳을 더 가깝게 둬도), 「휠체어·유모차」 실격, 「매워요」 실격,
  글 "주차 돼야 해요" 실격(create_run → execute_run 전체), 칩 다섯 개 내림·예외 칩 그대로(core), api 같은 결과(「좁아요」 preferred)

---

# #587 — 추천 막힘 조언용 run 정보 조회와 passed_count

조언 자체(대상 판정, 모델, 검증, 저장)와 `GET /runs/{runId}/advice` 라우터는 agent에 있다. recommend는 run 읽기 함수만 더했고
agent를 import하지 않는다(루트 리뷰 후속 수정, 2026-10-18 — 아래 "후속 수정").

## 후속 수정 (루트 리뷰, 2026-10-18)

- **라우터를 agent로 옮겼다.** 처음에는 recommend 라우터 → `flows.run_advice` → `agent.api.advise_run`이었고 recommend와 agent가 서로를
  import했다. 지금은 agent/router.py가 `recommend.api.get_run_meta`와 authz로 권한을 보고 agent.flows를 바로 부른다. recommend의
  `router.get_advice`, `flows.run_advice`, `deps.get_session_factory`(SessionFactoryDep)를 지웠다 — router·deps·flows의 import는 develop과
  같다. recommend → agent import 0개
- **passed_count**: `api.get_run_funnel`은 `{result_count, funnel, passed_count}`를, `api.simulate_filter`의 before·after는
  `{result_count, funnel, passed_count}`를 돌려준다. passed_count는 필터를 모두 통과한 곳의 수(상위 3곳을 고르기 전)이고
  `core.passed_count(result_count, funnel)` = 결과 수 + `core.RANKING_STAGE` 단계 탈락이다. 단계 라벨을 정하는 곳(`_run_pipeline`)과
  세는 곳이 같은 상수를 써서 라벨 문구를 바꿔도 셈이 그대로다. 깔때기 라벨과 화면 문구, 필터 규칙은 바꾸지 않았다.
  get_run_funnel의 result_count는 get_run_meta와 같은 기준(후보 수, done이 아니면 0)이라 이전 시도에서 게시된 후보가 남은 run은 그만큼
  passed_count도 크게 나온다(전과 같은 기준, 바꾸지 않았다)
- 테스트(`tests/test_run_reads_api.py`): 통과 다섯 곳·결과 3곳 판에서 passed_count가 저장 깔때기와 시뮬레이션 모두 5, 「좁아요」를 끄면 6.
  `core.RANKING_STAGE`를 다른 문구로 바꿔도 같은 값

## 구현

- `api.get_run_meta(db, *, run_id)`: `{run_id, map_id, category, requested_by, status, result_count, created_at,
  default_radius_walk_min, widen_limit_walk_min}`. agent가 대상 판정(완료, 결과 수), 요청자 확인, 반경 상한(core.WIDEN_LIMIT_MIN)에
  쓴다. result_count는 get_recent_runs와 같은 기준(후보 수, done이 아니면 0). 권한 판정 없음
- `api.get_run_evidence`에 `chip_id`를 더했다(키 없는 줄 중 「비싸요」 칩을 agent가 not_filtered로 가르려고). 다른 칸은 그대로다

## 루트에 알릴 것

- 명세 9절의 경로(recommend router → flows → agent.api)와 달리 라우터가 agent에 있다(위 후속 수정). 명세 문구는 고치지 않았다
- 필터 규칙, 깔때기, 스펙은 바꾸지 않았다. 계약 테스트의 KNOWN_MISSING·KNOWN_UNCOVERED에서 이 경로를 지우고 골든 패스(403, 204)와
  `test_run_advice_matches_the_openapi_spec`(같은 카테고리 run 3개 → 200, RunAdvice 스키마 검증, 다시 열어도 같음)에 넣었다
- `tests/test_run_reads_api.py`: get_run_meta 테스트, 없는 run NOT_FOUND 목록에 get_run_meta, get_run_evidence 기대값에 chip_id

---

# #585 — 추천 막힘 조언용 run 조회 3종과 읽기 전용 시뮬레이션

## 구현

- `recommend.api`에 `get_recent_runs`·`get_run_funnel`·`get_run_evidence`·`simulate_filter`. 네 함수 모두 권한을 판정하지 않는다(agent가 run 요청자를
  확인한 뒤 부른다, docstring에 적음). 없는 run은 `AppError NOT_FOUND`. 라우터·스펙 변경 없음.
- `_run_pipeline`이 지역(`_PipelineRegion`, regions 행의 사본)과 활성 근거 줄을 인자로 받는다. 읽는 곳은 `_pipeline_inputs` 하나이고, 시뮬레이션만
  반경 배율과 끌 줄을 넘긴다. 필터 순서·실격 규칙·깔때기 라벨은 그대로다. execute/widen/retry는 `_pipeline_inputs(db, run)`로 지금과 같은 입력을 넘긴다.
- `_excluded_place_ids(record_dismissed=False)`: 🚫한 곳을 `exclusions`에 쌓지 않고 집합에만 합친다. 결과 집합은 실행 때와 같다(가드레일 6).
- 테스트 `tests/test_run_reads_api.py`(15개): execute_run 깔때기·후보 고정, before = 실제 실행 결과, 줄 하나 끄면 그 실격만 풀림, 반경 배율 2배면 반경
  단계 탈락 감소, 제안·거절한 곳은 계속 빠짐, 호출 전후 recommend 테이블 전부와 event_log가 같음(실행 전·후 두 경우).

## 루트에 알릴 것

- **`docs/agent-v2.md` 10절 표와 다르다**: `get_run_evidence`는 표의 `is_requester_own` 대신 이슈 #585대로 `author_id`를 돌려준다(agent가 run의
  requested_by와 비교). 표를 고칠지 루트가 정한다.
- **`result_count`는 상위 3곳 선정 뒤의 수라 최대 3이다.** soft_relax의 "끄면 몇 곳이 더 남는가"는 깔때기의 「실격 조건 제거」 차이(또는
  `result_count` + 「상위 3곳 선정」 removed_count = 필터 통과 수)로 계산해야 한다. 통과 수 필드가 따로 필요하면 요청해 달라.
- **before는 다시 계산한 값이다**(last_funnel을 그대로 쓰지 않는다). 실행 뒤 지도에 핀이 생기거나 🚫가 달리면 마지막 실행 결과와 달라질 수 있다. 차이는
  같은 호출의 before/after로만 비교하는 것이 맞다. 저장된 마지막 실행은 `get_run_funnel`.
- `simulate_filter`에 선택 인자 `place_search`, `place_facts`를 더했다(생략하면 `recommend.deps`가 고른 실행과 같은 Gateway). 테스트와 agent 스텁 주입용이다.
- 입력 검증: 그 run의 근거 줄이 아닌 id(형식 오류 포함)는 `NOT_FOUND`, `radius_factor <= 0`은 `ValueError`. 배율 상한은 없다 — 반경 넓히기 상한(30분,
  `WIDEN_LIMIT`)을 넘는 배율 조언을 내지 않는 건 agent 몫이다. 배율은 모든 지역 원에 곱한다(v1은 원 하나).
- dev 스텁(`DevPlaceSearchGateway`)은 원 중심 150m 안에 고정 6곳만 만들어서 반경 배율을 바꿔도 결과가 같다. 반경 조언은 real 모드에서만 의미가 있다.
- 시간: 로컬 PostgreSQL, 가짜 Gateway와 dev 스텁 모두 1회 약 25ms(파이프라인 2번, execute_run 1회는 약 29ms). real 모드는 여기에 장소 검색·라벨 조회가
  2번씩 더 붙는다. soft_relax가 줄마다 부르면 줄 수만큼 before를 다시 계산한다 — 느려지면 여러 변경을 한 번에 받는 함수를 따로 연다.
- 백엔드 전체 테스트에서 `agent/tests/test_flows.py::test_daily_cleanup_deletes_old_runs_once_a_day` 하나가 실패한다. 이번 변경을 뺀 develop 상태에서도
  똑같이 실패해서 이번 작업과는 무관하다(agent 코드라 손대지 않았다).

---

# #569 — 실시간 핀 가게를 추천에서 제외

`flows._excluded_place_ids`가 `pins.api.list_live_kakao_place_ids(map_id)`의 카카오 ID마다 `places.api.own_places_by_kakao_id`로 자체 DB `place_id`를 찾아 기존 제외 집합에 합친다(다른 모듈 service·models 호출 없음). 실시간 핀이 없으면 places를 부르지 않는다.

- 깔때기: 새 단계 없음. 「이미 지도에 있는 장소」는 원래 별도 단계 없이 `_excluded_place_ids` 하나로 합쳐 「이미 제안·거절됨」(`removed_exclusions`)에서 세므로, 실시간 핀 가게도 거기에 합산된다.
- 요청자 제안·거절 이력, 개인 단위 규칙, 스펙·응답은 그대로. 이견 없음.

---

# #469 — 지난 추천 기록

## 구현

- `GET /maps/{mapId}/runs?category&limit` — `require_map_member()`(비구성원 404). **`requested_by == 나`인 run만**(가드레일 1), `created_at` 내림차순,
  limit 기본 20·최대 50(범위 밖 422), category 필터(없는 분류 422). 항목은 `RunSummary`(스펙 그대로).
- `candidate_count`/`published_count`는 `service.list_runs_for_requester` 한 쿼리에서 `candidates`를 run별로 집계해 outer join한다(N+1 없음,
  테스트가 SELECT 1회를 확인). `candidate_count`는 status가 `done`이 아니면 0, `published_count`는 상태와 무관하게 센다.
- `GET /runs/{runId}/result`: status가 `done`이 아니면 409 `RUN_NOT_FINISHED`(검사가 `NO_RESULTS`보다 먼저). 기존 흐름(execute 뒤 조회)은 `execute_run`이
  `done`으로 끝내므로 영향이 없다 — 골든 패스·계약 테스트가 그대로 통과한다.
- 마이그레이션 `0028_recommend_runs_history_idx`: `recommend_runs (map_id, requested_by, created_at DESC)` 인덱스. **down_revision은 작성 시점 develop head인
  `0024_evidence_lines_seq`다.** `0025_invite_revoke`(미병합 브랜치)가 먼저 머지되면 그 뒤로 down_revision을 옮겨야 head가 하나로 유지된다(머지 순서 확인 필요).
- `KNOWN_MISSING`(test_spec_route_coverage)·`KNOWN_UNCOVERED`(test_response_contract)에서 `GET /maps/{}/runs`를 지웠고, 골든 패스에 내 run만 보이는지·남의 run이
  안 보이는지를 넣었다.

## 루트에 알릴 것

- 같은 테스트 DB를 쓰는 pytest를 동시에 돌리면 `DROP TABLE` 데드락이 난다(이번에도 한 번 겪음) — `PINGO_TEST_DB`를 세션마다 다르게 준다.

---

# #190 — 후보·이름·라벨을 자체 장소 DB에서 읽기 (모델 호출은 ② 하나)

## 구현

- **포트 변경(`recommend/ports.py`)**: `PlaceFactsGateway.get_raw_facts(place_id)` → `get_facts(place_ids) -> Mapping[str, Sequence[FactLabel]]`
  (배치, 라벨 그대로). `PlaceSearchGateway`에 `get_names(place_ids)`를 추가했다(후보 응답의 `place_name`용).
- **실제 모드**: `RealPlaceSearchGateway` = `places.api.search_nearby_own`/`get_places`, `RealPlaceFactsGateway` = `places.api.get_facts`.
  후보의 place_id·좌표는 places에서 온다(candidates 행에는 그 둘과 라벨 checks만 저장). 카카오 실시간 경로
  (`search_nearby`·`get_raw_facts`·`resolve_place`)는 recommend 어디서도 부르지 않는다. 게이트웨이는 선택적 `db`를 받는다
  (테스트가 세션을 넘긴다; 운영은 places가 짧은 세션을 연다).
- **라벨**: `flows._run_pipeline`이 후보를 한 번에 `get_facts`로 읽고 `llm.label_place`를 **부르지 않는다**. 라벨이 없거나
  `confidence=unknown`이거나 known인데 값이 비어 있으면(`core.resolve_label`) unknown으로 보고 `unknown_policy`를 그대로
  적용한다 — 안전 조건은 제거, 취향 조건은 통과+`needs_check`(가드레일 8). 값 없는 known을 통과 쪽으로 읽지 않는다.
- **이름**: `GET /runs/{id}/result`의 `Candidate.place_name`을 `place_search.get_names`로 채운다(이전엔 항상 비어 있었다).
- **dev 모드는 그대로**: `DevPlaceSearchGateway`는 변하지 않았고(+`get_names`는 `{}`), `DevPlaceFactsGateway`는 빈 라벨을
  돌려줘 이전과 같이 전부 unknown이 된다.
- **llm 쪽**: `llm.label_place` 자체는 건드리지 않았다(v2 모델 라벨링용으로 남는다). 이제 recommend가 부르지 않을 뿐이다.

## 테스트

- `integration/test_recommend_own_places.py` 5개 — FakePlaces(`places.testing`)로 3개(unknown 안전 조건 제거/known 통과/이름·좌표가
  places에서 옴), **places.api 실제 구현**(적재 픽스처, PostgreSQL+PostGIS)으로 2개. 전부 `label_place` 호출 0회를 확인한다.
- `integration/test_places_no_kakao_leak.py` — 카카오 어댑터에 표식 값을 심은 채 real 게이트웨이로 실행해도: `label_place` 호출 0회,
  카카오 경로 호출 0회, ②(`plan_evidence`) 인자와 candidates 행에 표식 없음. real 게이트웨이에 원자료 메서드가 없음을 고정.
- `places/tests/test_gateways.py` 3개를 새 게이트웨이 계약에 맞췄다(places 소유 테스트 — recommend 게이트웨이를 검사하는 부분만).
- 단위: `core.resolve_label`.
- 마이그레이션 0017을 빈 DB에서 `alembic upgrade head`로 확인(places·place_facts 생성, head 단일).

## 확인 요청

- `PlaceStub.source`(#158 `place_source`)는 자체 DB 장소에는 카카오/네이버/구글 출처가 없어 real 모드에선 계속 null이다.
  가드레일 5의 "출처가 항상 붙는다"는 `place_source` enum(kakao|naver|google)이 자체 DB 출처(permit·tourapi)를 담도록
  스펙이 바뀌어야 성립한다 — 스펙은 루트 소관이라 건드리지 않았다.
- 이슈 "실제 소요"는 기입하지 못했다.

---

# #119 · #114 — dismissed 제외(가드레일 6)와 pins.models import 제거

## #119 — 요청자가 🚫한 장소를 `exclusions.reason='dismissed'`로 제외

- **`pins/api.py::list_disliked_place_ids(db, *, user_id, map_id, category) -> list[str]`(pins 소유 파일, 함수 추가만
  — pins 세션의 리뷰가 필요하다)**. 그 사용자가 이 지도·카테고리에서 against를 남긴 핀의 place_id(중복 없이 정렬).
  **소프트 삭제된 핀도 포함한다** — 다른 조회 함수와 달리 일부러 `deleted_at`을 거르지 않았다. 🚫는 이력이라
  핀이 지워져도 남아야 하고, 지워진 핀은 `list_place_ids_on_map`(살아 있는 핀만)에서 빠져 이게 없으면 거절한
  장소가 다시 추천된다. 핀이 살아 있는 동안은 기존 경로가 이미 막고 있었다 — 이번에 막는 건 삭제 뒤다.
- **`flows._excluded_place_ids(db, run)`** — execute/widen/retry에 똑같이 복붙돼 있던 "exclusions ∪ 지도 위 핀" 3블록을
  하나로 합치고, 그 안에서 위 함수 결과를 `dismissed`로 `add_exclusions`한다(이미 있는 조합은 건너뛰므로 반복 호출
  안전, 이미 `proposed`인 곳은 그대로). 대상은 **요청자 본인의 🚫만**이다 — 다른 구성원의 🚫는 근거 줄(required)
  → 실격 경로로 들어가 이미 반영된다(제외목록은 개인 단위, #42). funnel "이미 제안·거절됨"이 이 제외분을 센다.
- 테스트: pins 3개(본인 against만/삭제 핀 포함/빈 결과), recommend 3개(삭제된 🚫 핀의 장소가 후보에서 빠지고
  dismissed 행이 생김/타인의 🚫는 제외 아님/두 번 실행해도 멱등).
- 아래 "#108" 절 8번("절반만 구현했다")은 이 작업으로 해소됐다.

## #114 — `recommend/flows.py`의 `pins.models` import 제거

`publish_candidate`가 ORM 행 대신 `pins.schemas.Pin`을 돌려준다(멱등 경로·새 게시 경로 모두
`pins_api.get_pin_response_for_viewer`로 조립 — 존재·가시성 규칙이 `get_pin_for_viewer`와 같아 404 동작 불변).
Principal 조립은 `post_publish`에서 `flows._published_pin_response`로 옮겼고 라우터는 결과를 그대로 반환한다.
테스트는 스키마에 없는 `origin`/`place_id`를 DB 행에서 확인하도록 고쳤다. 이슈의 grep으로 recommend의 위반은 0건
(남는 출력은 `integration/` 테스트 픽스처뿐 — 모듈 코드가 아니다).

**[남은 일 — pins 후속 권고]** 근본 원인(이슈 본문 A안)은 그대로다: `pins.api.get_pin_for_viewer`와
`PinMutation.pin`이 여전히 ORM 행(`PinRow`)을 노출한다. 이번엔 지시대로 pins 시그니처는 바꾸지 않았다.
`shortlist/loaders.py`가 그 행의 `.map_id/.visibility/.created_by/.kind`를 쓰고 있어, 스키마 반환으로 바꾸려면
shortlist도 함께 고쳐야 한다 — pins·shortlist 공동 후속 이슈를 권한다. 다음 소비자가 같은 문제를 만나기 전에.

---

# #158 · #146 · #112 후속 — Candidate 가드레일5 필드, 반경 넓히기 폭, 숙소 제거 (마이그레이션 0015)

스펙(`docs/api-spec.yaml`·`constraints.md`)은 건드리지 않았다. 아래 "루트 확인" 항목만 루트 소관이다.

## 구현 범위

**#146 숙소 제거** — `schemas.Category`(=RecommendCategory)·`models.Category` enum·`flows.CATEGORIES`·
`constraints._ALL_CATEGORIES`에서 숙소를 뺐고 `capacity_min`(레지스트리·`VALUE_COMPARISON_UNSUPPORTED`)을
지웠다. readiness 응답 키는 음식점·카페·관광지 셋, 숙소로 run 생성 요청은 422.
`test_response_contract.py`·`test_constraints_contract.py`의 `KNOWN_DRIFT` 해당 항목을 지웠다
(후자는 딕셔너리 자체를 없애고 "문서에 없는 조건이 코드에 있으면 실패"로 단순화).

**기존 숙소 run 처리 방침(0015 upgrade)** — 숙소 run과 그 하위 행(`candidates`/`regions`/`evidence_lines`)·
숙소 `exclusions`를 삭제하고 enum에서 값을 뺀다. 이 테이블들은 요청자 개인의 작업 상태(근거 조립·비공개
후보·재시도 제외목록)라 추천 대상에서 빠지면 쓸 곳이 없다. **이미 게시된 핀은 pins 소유라 그대로**이고
게시 때 checks가 pins로 복사돼 있어 가드레일 5(게시 뒤 유지)가 깨지지 않는다. 지운 행은 downgrade로
복원되지 않는다(enum 값만 되돌림). 검증: 숙소 run 1·카페 run 1을 넣고 upgrade → 숙소 쪽만 사라짐,
downgrade → enum 4값 복귀, 재upgrade 정상.

**#158**
1. `candidates.reason`(text, nullable)·`place_source`(jsonb, nullable) 추가. `recommend_runs.default_radius_walk_min`
   (int, 기본 15)도 0015에 같이 넣었다(아래 3번).
2. `member_fulfillment`를 스펙 모양 `{satisfied, total, by_member[{user_id, satisfied}]}`로 채운다.
   **`total` 계산 근거**: 스펙 정의("조건을 남긴 구성원")를 "이번 선호 기준(`criteria`가 True인 fact_key) 중
   자기가 지지한 것이 하나라도 있는 구성원"으로 옮겼다. 지지 = 그 값의 장소에 ♥했거나 그 fact_key를
   선호 사유로 직접 쓴 것(#112 기존 규칙 그대로). ♥만 누르고 기준에 안 든 사람·반대만 한 사람은 집계 밖.
   **`satisfied`**는 자기 조건을 *전부* 이 후보가 known+참으로 충족한 구성원 수 — 일부만 맞으면 세지 않는다
   (부풀리지 않는 쪽으로 정함, 스펙은 "자기 조건을 만족"이라고만 함 → 루트 확인). 옛 모양
   `{member_id:[fact_key]}`은 사라졌고 0015가 기존 행의 값을 `{}`로 비운다(`{}`는 응답에서 필드 생략).
   `display_name`은 auth 조회가 없어 못 채운다(EvidenceLine과 같은 갭).
3. **반경 넓히기** — `core.next_default_radius_walk_min`(+5분, 상한 30분, 초과 시 409 `WIDEN_LIMIT`). 상수는
   `core.DEFAULT_RADIUS_WALK_MIN/WIDEN_STEP_MIN/WIDEN_LIMIT_MIN`(constraints.md 표 그대로). 누적 상태는
   `run.default_radius_walk_min`, 지역 반경은 거기서 `분×80m`로 파생. `POST /runs/{runId}/widen`이 이제
   `RecommendRun`(+`default_radius_walk_min`)을 202로 돌려준다(이전엔 본문 없음). 옛 `widen_radius`(2배)는 삭제.
   v1엔 사람이 명시한 원이 저장되지 않아 저장된 원이 전부 기본값 원이다 — 명시적 원이 생기면 그 원은
   건드리지 않도록 `widen_run`을 좁혀야 한다(가드레일 4).
4. 재시도 상한은 이미 5회(`core.ATTEMPT_LIMIT`) — 변경 없음.
5. `recommend/api.py` 신설 — `delete_evidence_lines_by_author(db, *, user_id) -> int`(모든 run의 그 사용자 근거 줄 삭제).
   커밋은 호출자(탈퇴 흐름)의 get_db가 한다. **auth 쪽 탈퇴 흐름이 이 함수를 부르는 배선은 이번 범위 밖이다.**
6. `reason` = `core.build_reason` — 통과한 체크·충족한 선호 라벨에서 조립한 한 줄, **모델 호출 없음**.
   "실격 조건 통과: A, B · 선호 충족: C (n/m명)". known으로 통과한 것만 말하고, unknown·불통과·
   `price_bucket`(값 비교를 못 해 "표시만"인 키)은 말하지 않는다. 말할 게 하나도 없으면 고른 과정을
   그대로 적는다("반경 안 후보 중 활성 실격 조건에 걸리지 않은 곳이에요"). 표시 이름은
   `constraints.PASSED_LABELS`(8개: 현재 레지스트리 키 전부) — **#171에서 키를 늘릴 때 같이 채워야 한다.**
   `test_every_comparable_fact_key_has_a_reason_label`이 빠진 키를 잡는다.
7. `place_source` — `PlaceStub.source`(선택, `{provider, url?}`)를 그대로 싣는다. dev 스텁은 출처가 없어
   **항상 null**이다(지어내지 않는다). places(#14)가 실구현될 때 채워야 가드레일 5의 "출처가 항상 붙는다"가 성립한다.

**#112 후속** — 선호 사유 작성자가 같은 fact_key의 반대 집합(False 장소에 ♥)에 들어 +1−1로 상쇄되던 것을
`_member_support`에서 작성자를 반대 집합에서 빼는 것으로 정리했다(말로 쓴 선호가 ♥ 이력보다 우선). 다른
사람의 반대 ♥는 그대로 상쇄된다. 테스트 2개.

## 루트 확인 / 다른 세션에 넘기는 것

- **[pins 세션 필요] 게시 시 3필드 복사**: `pins.api.create_ai_pin`에 `reason`·`member_fulfillment`·`place_source`
  파라미터가 없고 pins에 해당 컬럼도 아직 없다(0016은 pins 몫). 그래서 `publish_candidate`는 이번에 그
  필드를 넘기지 못했고, 이슈 완료 조건의 "pins로 3필드가 복사되는지 통합 테스트 1개"는 **미완료**다.
  pins가 `create_ai_pin(..., reason: str | None = None, member_fulfillment: dict | None = None,
  place_source: dict | None = None)`을 열면 `flows.publish_candidate`에서 `candidate.reason/
  member_fulfillment/place_source`를 그대로 넘기는 한 줄 추가 + 통합 테스트로 닫는다. 스키마는
  `MemberFulfillment`/`PlaceSource` 모양 그대로 저장하면 된다(필드가 비어 있으면 null/`{}`).
- **[llm] `capacity_min` 잔존**: #146 본문은 `backend/llm/schemas.py:29`(사유 구조화 출력 fact_key 목록)의
  `capacity_min` 제거도 적었지만 llm은 남의 모듈이고 이번 지시 범위가 아니어서 건드리지 않았다. recommend는
  이제 그 키를 레지스트리에 갖지 않으므로 llm이 `capacity_min`을 내놓아도 `HARD_REGISTRY` 카테고리 필터에서
  걸러져 실격에 쓰이지 않는다(값이 조용히 버려짐). llm 세션이 지워야 한다.
- **[문서] `docs/data-model.md`** `candidates` 블록에 `reason`·`place_source` 컬럼이, `recommend_runs` 블록에
  `default_radius_walk_min`이 없다(스펙엔 있음). 문서는 루트 소관이라 고치지 않았다 — 반영 필요.
- `MemberFulfillment.satisfied` 정의(위 2번)와 `total`의 "조건을 남긴 구성원" 해석 확인 요청.
- 마이그레이션 번호: 0015는 #146·#158 공용(이슈 지시대로). 0016은 pins.
- **이슈 본문 "실제 소요"는 채우지 못했다** — 작업 시간 기록이 없다. 담당자가 기입.

**검증**: `PINGO_TEST_DB=pingo_test_recommend python -m pytest --ignore=.venv` 633 passed / 1 skipped
(착수 전 614 passed / 1 skipped). `alembic upgrade head`/`downgrade`/재`upgrade` 실제 PostgreSQL로 확인(위 시나리오).
`ruff`는 이 환경에 설치돼 있지 않아 돌리지 못했다. `git merge origin/develop` — 이미 최신, 충돌 없음.


# #112 — 선호 순위 점수 계산과 상위 3곳 선정 (#99 후속)

## 구현 범위

이슈 지시(`docs/constraints.md`의 "선호 점수 계산 (③-b)" 절 + 이슈 본문 요약)를 그대로
따랐다 — `recommend/core.py`에 `HeartedPlace`/`ScoredCandidate` + `build_preference_criteria`/
`score_candidates`/`build_member_fulfillment`/`select_top_candidates` 4개 순수 함수를 추가하고,
`flows.py::_run_pipeline`이 `llm_service.rank_candidates`(항등 순서 스텁) 대신 이 함수들을
쓰도록 배선했다. `member_fulfillment`도 이번 점수 계산과 연결되는 자리라고 판단해 같이 채웠다
(아래 "꼭 읽어야 할 것" 3번).

- **문서 갭(착수 시점 기록 — 이후 루트가 절을 추가해 해소됨)**: 이슈 본문은 "규칙 정본은 `docs/constraints.md`의 '선호 점수
  계산 (③-b)' 절"이라고 안내하지만, 실제로 그 문서를 읽어보면 그 절이 존재하지 않는다(있는
  건 "조건별 정의" 실격 표뿐). `docs/architecture.md:273`도 같은 절을 참조하고 있어 — 아마
  `docs/CHANGELOG-api.md`에 없는 걸 보면 문서에 반영하는 걸 깜빡한 것으로 보인다. 이 세션은
  `gh issue view 112`로 이슈 본문을 직접 읽어 규칙(①~⑤ 단계, 점수 공식, 3단계 tie-break)을
  확인하고 그대로 구현했다 — **`docs/constraints.md`에 이 절을 실제로 추가하는 건 루트 소관
  (값 변경은 루트만)이라 이번 세션이 하지 않았다.**
- **`recommend/core.py`** — 위 4개 함수. `HeartedPlace`(checks + member_ids)와
  `ScoredCandidate`(place_id/score/region_label/lat/lng) 두 dataclass도 추가.
- **`recommend/models.py`/마이그레이션 `0013_regions_anchor_points`** — `regions.anchor_points`
  (JSONB, `[[lat, lng], ...]`) 신규. 3단계 tie-break("그 무리의 기준 핀들까지 거리 평균")를
  계산하려면 병합 전 원본 anchor 좌표가 필요한데, `regions`는 병합된 `center_lat/lng`만 갖고
  있었다 — `candidates.lat/lng`·`regions.center_lat/lng`와 같은 종류의 차원 압축 결정이다.
  `flows.py::_default_circle_and_anchors`(옛 `_default_circle`을 이름까지 바꿔 확장)가
  `create_run` 시점에 이 값을 채운다.
- **`pins/api.py::list_liked_pins_with_checks`(신규, pins 소유 파일)** — ♥(like) 반응을 받은
  핀들의 `checks`(#124가 채운 값)와 ♥ 누른 구성원 집합을 묶어 돌려준다. 기존 세션들이
  `count_reacted_users` 등을 추가한 것과 같은 선례를 따랐다 — **pins 세션의 리뷰가 필요하다.**
  루트 검수 반영: `requested_by`를 받아 `service._visible_pins_clause`(공개 핀 + 본인 비공개
  핀)로 거른다 — 타인의 비공개 후보에 붙은 ♥/라벨이 요청자의 선호 프로필에 섞이지 않는다(가드레일 1).
  `flows._run_pipeline`이 `run.requested_by`를 넘긴다.
- **`flows.py::_run_pipeline`** — 기존엔 활성 실격(hard) 라벨만 붙였는데, 이제 선호(soft) 라벨
  (`constraints.SOFT_FACT_KEYS`)도 모든 후보에 붙인다 — 그래야 점수 계산에 쓸 known 값이
  생긴다. funnel에 "상위 3곳 선정" 단계를 추가했다(최종기획안.md 239행 "남은 후보 5곳 →
  상위 3곳 제시"와 맞춤).
- **테스트**: `test_core.py`에 4개 함수 전부(값 갈릴 때/동점일 때/조사 안 됐을 때/실격 사유로
  등록된 라벨/명시적 선호/구성원 수 diff/한 사람 중복 집계/동네 배분이 점수를 못 이기는 것/
  거리는 합이 아니라 평균/기준 핀 없을 때 ValueError) 56개 신규 테스트. `test_flows.py`의
  기존 region 헬퍼(`_make_region`)에 `anchor_points` 기본값을 추가해 회귀를 막았다.

**검증**: `pytest recommend/tests -q` 123 passed. 백엔드 전체 `pytest --ignore=.venv -q` 561
passed/1 skipped. `alembic upgrade head` 정상(0013이 head). `python -c "import main"` 정상.
`ruff check`는 이 세션이 건드린 파일 전부 통과 — `alembic/versions/0013_...`의 `typing.Union`/
`Sequence` 경고와 `core.py`의 `typing.Mapping`/`Sequence` 경고(UP035)는 0008 마이그레이션·
`recommend/ports.py`가 이미 쓰는 것과 같은 기존 컨벤션이라 그대로 뒀다(#108 세션이 같은
판단을 내린 전례 그대로).

## 루트 검수 반영 (2026-09-30)

- **[필수] 가드레일 1** — 위 pins 항목. 테스트: `pins/tests/test_pins_api.py`의
  `test_list_liked_pins_with_checks_excludes_other_users_private_pin`(타인 비공개 핀의 ♥는 안
  들어감) / `..._includes_own_private_pin`(본인 것은 들어감).
- **선호 사유 작성자를 지지 구성원에 포함** — `flows`가 `preferred` 근거 줄의
  `(fact_key → author_id 집합)`을 `preferred_authors`로 넘기고, `core._member_support`가 그
  작성자를 그 fact_key의 지지자에 더한다(`score_candidates`/`build_member_fulfillment`/
  `build_preference_criteria` 공통). 집합이라 ♥도 누르고 사유도 쓴 사람은 1명으로 센다.
  `docs/constraints.md` "선호 점수 계산" 5번은 ♥ 없는 작성자를 지지자로 세는지 명시하지 않는다 —
  "구성원 단위로 센다"(한 사람 1)와는 충돌하지 않지만 **문구로 못 박을지는 루트 확인 필요.**
- **소프트 키만 사용** — `build_preference_criteria`/`_member_support`가
  `constraints.SOFT_FACT_KEYS`에 속한 fact_key만 쓴다(하드 체크의 `passed`는 "실격 아님"이라
  라벨 값과 뜻이 다르다). `preferred` 사유의 키도 소프트가 아니면 무시한다.
- **0013 backfill** — 컬럼 추가 뒤 `anchor_points='[]'`인 기존 행을 `[[center_lat, center_lng]]`로
  채운다(원본 anchor 목록은 복원 불가 — 중심을 대표 기준 핀으로 삼는 근사).
- **[기록만·한계] `regions[0]` 하나만 쓴다** — `_run_pipeline`이 지역 여러 개를 다루지 않고
  `regions[0]`의 label/anchor만 `select_top_candidates`에 넘긴다(모든 후보가 같은 region_label이라
  "아직 안 뽑힌 동네 우선" tie-break가 사실상 동작하지 않는다). 지금은 v1 기본 원 하나뿐이라 실해는
  없지만, **실제 장소 데이터(#34)를 연결해 후보가 여러 원에 걸치게 되면 후보→region 매핑과
  region별 anchor 전달을 함께 고쳐야 한다.**

## 꼭 읽어야 할 것 (이 세션이 직접 정한 것 — 문서에 없어 판단이 필요했던 지점)

1. **선호 기준이 정확히 반반으로 갈릴 때(③단계) 그 라벨을 기준에서 뺐다.** 이슈 본문은
   "많은 쪽을 택한다"만 말하고 동점은 다루지 않는다. 신호가 없다고 보고 배제하는 쪽을
   택했다(True로 임의로 밀어붙이면 근거 없는 선호를 지어내는 셈이라 더 위험하다고 판단) —
   `core.build_preference_criteria` docstring에 기록. **다른 처리(예: True 우선)가 맞다면
   루트 결정 필요.**
2. **`member_fulfillment`의 JSON 모양을 이 세션이 정했다.** `api-spec.yaml`/`data-model.md`
   어디에도 스키마가 없다(이슈 본문도 "필요하면 채워달라"로 열어뒀다) — `{member_id: [충족한
   fact_key, ...]}`로 정했다(점수에 실제로 기여한 구성원만 포함, 그냥 ♥한 사람 전부가 아니다).
   API 응답(`recommend/schemas.py::Candidate`)엔 아직 이 필드가 없어 FE에 노출되지 않는다 —
   노출하려면 스키마·`docs/api-spec.yaml`에 추가하는 결정이 먼저 필요하다.
3. **선호(soft) 라벨링을 이번에 `_run_pipeline`에 새로 추가했다** — 이슈 범위(점수 계산)를
   넘는 변경으로 보일 수 있어 명시한다. 기존 코드는 활성 실격(hard) 라벨만 `label_place`에
   요청했는데, 점수 계산에 쓸 known 선호 라벨이 하나도 없으면 이번 기능 전체가 항상 0점만
   내므로 반드시 같이 필요했다. dev 스텁(`place_facts.get_raw_facts`가 항상 `{}`)에서는 이
   변경도 결과적으로 항상 unknown이라 실제 동작 차이는 없다(이슈 본문의 "동작 확인은 아직
   못 한다"와 같은 이유).
4. **`select_top_candidates`가 매 tie-break마다 거리 평균을 "남은 후보 전부"에 대해 미리
   계산한다** — 점수만으로 승자가 갈리는 라운드에서도 기준 핀 없는 후보가 섞여 있으면
   ValueError가 난다. 의도적이다(이슈 본문 "0개라면 반경 계산이 깨진 것이므로... 넘어가지
   않는다"를 엄격하게 해석) — 운 좋게 tie-break에 안 걸렸다고 깨진 상태를 숨기지 않는다.

## 루트 확인·결정 필요 (모아서)

1. (해소) `docs/constraints.md`의 "선호 점수 계산 (③-b)" 절은 루트가 추가했다 — 이 세션 초기엔
   없었다. 동점 처리·작성자 지지 여부(위 "루트 검수 반영")만 그 절에 명시할지 확인 필요.
2. **위 "꼭 읽어야 할 것" 1·2번** — 동점 처리, `member_fulfillment` 모양.
3. **`pins/api.py::list_liked_pins_with_checks`** — pins 세션 리뷰 필요(위 구현 범위 참고).
4. **`regions.anchor_points` 컬럼을 새로 추가한 것** — `data-model.md`에 반영할지 여부(이전
   `regions.geom` 미도입 결정과 같은 종류, 이미 그때도 루트 확인 대기 중이었다).

---

# #124 — publish_candidate가 candidate.checks를 pins로 복사

## 구현 범위

#57 결정(data-model.md 51·57·288행)을 배선만 했다 — `recommend/flows.py::publish_candidate`가
`pins_api.create_ai_pin(...)` 호출에 `checks=candidate.checks`를 추가로 넘긴다. 그 외 로직
(인가 순서, 멱등 경로, 이벤트 처리)은 그대로다. `pins.api.create_ai_pin`이 자기 쪽에서
`pins.schemas.Check`로 다시 검증해 저장한다(경계 검증 — recommend/pins 두 `Check` 스키마가
같은 필드 모양(`fact_key`/`label`/`passed`/`confidence`/`needs_check`)이라 그대로 통과한다).

**pins 쪽 계약과의 타이밍**: 착수 시점엔 pins 쪽 `create_ai_pin`/`Pin` 모델에 `checks`가 아직
없었다(이 저장소가 git이 아니라 브랜치 격리가 없어 그 상태가 바로 보였다). 이 세션은
recommend만 배선하고 실패를 감수하기로 사용자와 합의했는데, 구현 도중 pins 쪽 별도 작업이
합쳐져 지금은 두 쪽 다 맞다 — 별도 조정 없이 자연히 정리됐다.

- **뺀 것**: `pins.source_run_id`(같은 #57 결정 대상)는 이번 이슈 범위 밖이라 넣지 않았다.
  `run_id`를 아는 건 recommend뿐이라, 넣으려면 `create_ai_pin`에 `run_id`(또는
  `source_run_id`) 파라미터를 새로 추가해야 한다 — 별도 이슈로 진행 요망.
- **회귀 테스트**: `recommend/tests/test_flows.py::test_publish_candidate_copies_candidate_checks_to_pin`
  — 실제 PostgreSQL 왕복으로 (1) 게시된 핀의 checks가 candidate.checks와 같은지,
  (2) 게시 후 candidate.checks를 바꿔도 핀 쪽은 그대로인지(write-once) 확인한다.
- **검증**: `pytest recommend/tests -q` 102 passed, 백엔드 전체 `pytest --ignore=.venv -q`
  519 passed/1 skipped, `ruff check` 클린(`recommend/flows.py`/`recommend/tests/test_flows.py`).

---

# #108 — 코어 파이프라인(`llm` 스텁 대상 통합)

## 구현 범위

`#108` 지시(“recommend 코어 파이프라인을 llm 스텁 대상으로 구현해달라”)를 그대로 따랐다 —
`llm.service.plan_evidence/label_place/rank_candidates` 스텁을 실제로 호출하고, places/seeding은
기다리지 않고 dev 스텁으로 그 자리를 메웠다.

- **`recommend/models.py`** — `evidence_lines`/`regions`/`exclusions` 추가. `recommend_runs`에
  `last_funnel`(JSONB, data-model.md엔 없음) 추가. `candidates.region_id`에 이제 FK를 건다
  (`regions`가 생겼으므로).
- **`recommend/constraints.py`(신규)** — `docs/constraints.md` 표 전사(authz/policy.py가
  permissions.md를 전사하는 것과 같은 원칙). 카테고리별 적용 대상 fact_key, `unknown_policy`.
- **`recommend/ports.py`/`recommend/deps.py`(신규)** — `PlaceSearchGateway`/`PlaceFactsGateway`
  두 포트 + dev 스텁(`common.adapters.select()`, `settings.places_mode` 재사용). 실제 장소
  데이터가 아니다 — 아래 "꼭 읽어야 할 것" 참고.
- **`recommend/core.py`** — 순수 함수 전부 추가: `check_readiness`/`required_count`/
  `assemble_evidence`/`circles_all_overlap`/`region_signature`/`merge_circles`/`widen_radius`/
  `is_within_any_region`/`build_check`/`apply_disqualifier_filters`/`funnel_counts`/
  `check_retry_limit`.
- **`recommend/service.py`** — recommend 소유 테이블 CRUD 전부(run/evidence/region/candidate/
  exclusion).
- **`recommend/flows.py`** — `get_readiness`/`create_run`/`list_evidence`/`patch_evidence`/
  `confirm_regions`/`execute_run`/`widen_run`/`retry_run`/`get_result` 추가(`publish_candidate`는
  그대로 유지).
- **`recommend/loaders.py`(신규)** — run 하위 엔드포인트(mapId가 URL에 없다)를 위한
  `authz.guard.require_with_principal()` 로더.
- **`recommend/router.py`(신규)** — `docs/api-spec.yaml` `recommend` 태그 엔드포인트 9개 전부.
  `main.py`의 주석 처리된 `include_router` 줄도 풀었다.
- **마이그레이션**: `alembic/versions/0008_evidence_regions_excl.py`.
- **다른 모듈에 추가한 함수(아래 "루트 확인 필요"에도 다시 정리)**:
  `pins/api.py::count_reacted_users`/`get_category_pin_coordinates`/`list_reasoned_reactions`,
  `maps/api.py::count_members`.
- **`common/tests/test_adapter_assembly.py`**: 새 포트 2개(`recommend.PlaceSearchGateway`/
  `PlaceFactsGateway`)를 `MISSING_REAL`에 등록(이 파일 자체가 "새 포트 추가 시 여기 등록"을
  전제로 설계된 회귀 테스트라 다른 모듈 파일이어도 직접 고쳤다).
- **테스트**: `test_core.py`/`test_constraints.py`/`test_service.py`/`test_flows.py`/
  `test_router.py`(신규, TestClient 골든 패스 — run 생성→evidence→지역확인→execute→result→publish).

**검증(Docker로 PostGIS 띄운 뒤)**:
```
cd backend && ./.venv/Scripts/python.exe -m pytest --ignore=.venv -q
```
→ **496 passed, 1 skipped**(전체 백엔드, 3회 반복 확인 — 안정적). `recommend/tests`만 92
passed. `ruff check`는 이 세션이 새로 쓴 파일 전부에 대해 통과 — 남은 경고 2종류
(`B008` Depends-as-default, `UP035` typing.Mapping/Sequence)는 기존 코드베이스 전체가 이미
쓰는 컨벤션과 정확히 같은 패턴임을 직접 대조 확인하고 그대로 뒀다(예: shortlist/loaders.py의
Depends 기본값, authz/policy.py·common/geo.py·llm/service.py의 typing.Mapping/Sequence).
`alembic upgrade head` 정상(0008이 head). `python -c "import main"` 정상.

## 꼭 읽어야 할 것 (v1 스텁이 만든 구조적 한계 — 실제 모델/장소 데이터가 오면 반드시 재검토)

1. **후보 풀 확보(`PlaceSearchGateway`)와 장소 원자료(`PlaceFactsGateway`) 둘 다 진짜 데이터가
   아니다.** `places`(#14)/`seeding`(#13)이 없어 `recommend/deps.py`의 dev 스텁이 이 자리를
   메운다 — `PlaceSearchGateway`는 반경 중심에서 고정 오프셋 6곳에 합성 `place_id`를 만들고,
   `PlaceFactsGateway`는 항상 빈 dict를 반환한다(그래서 라벨링은 늘 `unknown`이고
   `unknown_policy`로만 분기된다 — architecture.md 3절이 예상한 그대로 작동은 하지만, 실제
   추천 품질과는 무관하다). **`places`가 실구현되면 이 두 스텁을 교체하는 게 최우선**이다 —
   지금 상태로는 "필터 순서·이벤트·권한 배선이 도는 것"만 증명하지, 실제 추천 결과의 의미는
   없다(recommend/CLAUDE.md 우선순위 절이 원한 바로 그 순서 — 스텁으로 통합부터).
2. **반경 사유(circle_anchor_pin_id/circle_radius_m)가 v1에서는 절대 채워지지 않는다.**
   `llm.service.plan_evidence` 스텁은 `EvidenceLine(**raw_reason)`을 그대로 통과시킬 뿐 구조화를
   하지 않는다 — 자유 텍스트(반응 reason_text)에서 "해운대 기준 도보 5분" 같은 반경 사유나
   `fact_key`를 뽑아내는 건 실제 모델(#12)이 붙어야 가능하다. 그래서 `flows.create_run`은
   **모든 run에 대해 예외 없이 "기본값 원"(그 카테고리 핀들의 중심 좌표, 반경
   `DEFAULT_REGION_RADIUS_M=2000`m 고정)을 만든다** — 5-6-1 겹침 판정(`region_signature`/
   `circles_all_overlap`)과 `REGION_CONFLICT` 409 경로 자체는 구현·단위테스트로 커버했지만,
   실제 통합 경로에서는 항상 원이 0~1개라 트리거될 일이 없다(`confirm_regions`가 매번
   무충돌 200으로 끝난다). **모델이 실제로 반경 사유를 구조화하기 시작하면 이 기본값 fallback을
   "명시적 반경 사유가 하나도 없을 때만" 쓰도록 좁혀야 한다** — 지금은 유일한 경로라 항상 쓰인다.
   - **연쇄 효과 — `widen_radius`(가드레일4)**: "반경을 넓히는 것은 사람이 하고, 기본값 원만
     자동으로 넓힌다"는 원칙에서 "기본값 원 vs 사람이 명시한 원"을 구분해야 하는데, 위 이유로
     v1은 그 구분을 할 수가 없다 — 그래서 `flows.widen_run`은 **run의 원 전부를 무조건
     2배(`core.WIDEN_FACTOR`)로 넓힌다.** 모델이 붙어 명시적 원이 실제로 생기면 이 함수를
     "기본값 원만" 넓히도록 좁혀야 한다. **배율 2.0 자체도 문서에 없는 이 세션의 임의값** —
     루트가 실제 배율을 정해주면 좋겠다.
3. **`price_bucket`/`capacity_min` 실격 판정이 "표시만" 하고 절대 실패시키지 않는다.**
   `docs/constraints.md`는 이 둘을 "1인/음료/1박 상한 비교", "3인 이상 수용" 같은 **값 비교**로
   정의하는데, `docs/data-model.md`의 `evidence_lines` 스키마엔 badge/fact_key/text/circle_*뿐
   사용자가 명시한 **기준값**(가격 상한이 얼마인지, 인원이 몇 명인지)을 담을 컬럼이 없다.
   `recommend/constraints.py::VALUE_COMPARISON_UNSUPPORTED`로 이 둘을 명시적으로 격리하고
   `_passes_hard_check`가 항상 `True`를 반환하게 했다 — Check 자체(라벨·confidence)는 정직하게
   노출하지만 실격 판정에는 못 쓴다. **evidence_lines에 값 컬럼을 추가하거나 llm의 구조화
   출력에 임계값을 싣는 결정이 나야 이 둘을 실제로 실격 필터에 쓸 수 있다.**
4. **`member_fulfillment`(가드레일5 "구성원 충족 집계")가 항상 빈 `{}`다.** 3번과 같은 종류의
   갭 — "구성원 각자가 어떤 선호를 요구했고 이 후보가 그걸 몇 명분 충족하는지" 집계하려면
   구성원별 선호 요청이 구조화된 형태로 있어야 하는데, evidence_lines는 badge='preferred'
   텍스트만 있고 "누가 어떤 fact_key를 원했는지" 구조가 없다. 이것도 3번과 같은 스키마 결정이
   먼저 필요하다.
5. **인가 — `recommend.request` 액션을 run 하위 엔드포인트 전부(evidence 조회/토글·지역확인·
   실행·결과조회·반경넓히기·재시도)에 재사용했다.** `docs/permissions.md`/`authz/policy.py`가
   이 세부 액션들을 개별 선언해두지 않아서다 — `require_map_member()`/`require_on_map()`은
   `mapId`가 URL에 있는 라우트에만 쓸 수 있는데(하드코딩된 `Path(...)` 전제, `authz/guard.py`
   docstring 참고), 위 엔드포인트들은 `runId`만 있다. 그래서 `recommend/loaders.py::load_run`
   (run을 읽어 `Resource(type="map", map_id=run.map_id)`를 채우는 로더) +
   `authz.guard.require_with_principal("recommend.request", load_run)` 조합으로 "구성원이면
   전부 허용"을 구현했다 — 비구성원은 여전히 404, 구성원이면 항상 통과(세부 액션 구분 없음).
   **"누가 실행/재시도/반경넓히기를 할 수 있는가"가 "구성원 누구나"로 충분한지, 아니면
   `candidate.requested_by`처럼 author 제약이 필요한지는 루트 결정이 필요하다** — 지금은 남의
   run도 아무 구성원이나 실행/재시도할 수 있다.
6. **`patch_evidence`는 권한 없는 토글이 하나라도 섞이면 요청 전체를 403으로 거절한다**(부분
   허용/조용한 무시가 아니다) — `docs/api-spec.yaml`이 이 엔드포인트에 `Forbidden`을 명시적으로
   선언해뒀다는 점에 근거한 해석이다(`contracts/mocks`의 목 서버는 조용히 무시하지만, 그건
   403 계약이 확정되기 전에 쓰인 것으로 보인다).
7. **`regions` 테이블에 `docs/data-model.md`의 `geom geography` 컬럼을 두지 않았다.** 대신
   병합된 원을 `center_lat`/`center_lng`/`radius_m`(평범한 float/int)로 저장한다 —
   `candidates.lat/lng`(이전 세션 결정)와 같은 "차원 압축" 논리이지만, 이번엔 컬럼을 아예
   PostGIS 타입에서 float으로 바꾼 것이라 이전 결정보다 이탈 폭이 크다. **data-model.md에
   반영할지, 아니면 이후 `regions.geom`을 실제로 채우는 세션이 되돌릴지 루트 결정이 필요하다.**
8. **가드레일6 "이미 거절된 장소"의 절반만 구현했다.** `exclusions.reason='proposed'`(다시
   추천 받기 루프)는 `retry_run`이 채운다. `reason='dismissed'`(직접 찍은 핀에 🚫 반응을 남긴
   장소)는 구현하지 않았다 — pins에 "이 사용자가 어떤 place_id에 반대했는지" 조회 함수가 없다.
   **필요하면 `pins/api.py`에 함수를 하나 더 추가해야 한다(아래 "루트 확인 필요" 5번).**
9. **`run.candidates_ready`(개인 채널)만 발행한다.** `run.progress`(8단계 진행)·`run.failed`는
   구현하지 않았다 — v1은 실제 비동기 파이프라인이 없어(요청 안에서 전부 동기 처리) 여러 단계에
   걸쳐 진행률을 보고할 실질적인 지점이 없고, 실패는 `AppError`로 곧장 HTTP 에러가 되어
   `run.failed` 이벤트로 별도 알릴 상태 자체가 안 남는다.

## 루트 확인·결정 필요 (모아서)

1. **기본값 반경 원의 반경값(2000m)과 위젯 배율(2.0)** — 둘 다 이 세션이 문서 근거 없이 정한
   값이다(위 2·2번 항목).
2. **`price_bucket`/`capacity_min` 임계값을 어디에 저장할지** — `evidence_lines` 스키마 확장
   또는 llm 구조화 출력 확장(위 3·4번 항목, `member_fulfillment`도 같이 풀린다).
3. **run 하위 엔드포인트(evidence/지역확인/실행/결과/반경넓히기/재시도)의 정확한 인가 수준** —
   "구성원 누구나"로 충분한지, `candidate.requested_by`처럼 author 제약이 필요한지(위 5번).
   필요하다면 `docs/permissions.md`/`authz/policy.py`에 세분화된 액션 이름을 추가하는 게
   `recommend.request` 재사용보다 나을 수 있다.
4. **`regions.geom`(PostGIS) 컬럼을 아예 안 둔 결정**(위 7번) — data-model.md 반영 여부.
5. **가드레일6 "거절된 장소" 완성** — `pins`에 "이 사용자가 반대(🚫)한 place_id 목록" 조회
   함수가 필요하다(위 8번). `pins/api.py`가 아직 없어 이번엔 만들지 않았다 — pins 세션 몫으로
   남긴다.
6. **(이관) readiness의 N(#32) 정의** — `maps.api.count_members`로 "지도 전체 구성원 수"를
   썼다. #32 자체가 여전히 미결이라 이 값이 최종 정의가 맞는지는 그 결정이 나야 안다.
7. **`pins/api.py`·`maps/api.py`에 이번에 추가한 함수 4개**
   (`count_reacted_users`/`get_category_pin_coordinates`/`list_reasoned_reactions`/
   `count_members`) — 각 모듈 소유 파일이라 그 세션들의 리뷰가 필요하다. 전부 읽기 전용 집계
   함수이고 기존 함수(`get_coordinates_for_pins` 등)와 같은 패턴으로 맞췄다.
8. **(이관, 이전 세션이 이미 보고) `pins.api.create_ai_pin`의 이벤트 타입 버그** — 여전히
   `flows.py`에서 우회 중, pins 세션이 근본 수정할 항목.

---

# PR #71 멘토 리뷰 대응 — `publish_candidate` 슬라이스

## 구현 범위

`recommend/mentor-review-plan.md`는 이 모듈 전체가 아니라 **`flows.py::publish_candidate`
한 함수(「지도에 올리기」)만** 다루는 설계 문서였다 — 착수 조건으로 "`recommend_runs`/
`candidates` 테이블과 `recommend/service.py`·`core.py`가 최소 스켈레톤으로 존재"를 걸어뒀는데,
이 세션 시작 시점엔 그것도 없었다(`recommend/`엔 `CLAUDE.md`뿐). 그래서 그 스켈레톤부터
같이 만들었다:

- **`recommend/models.py` (신규)** — `recommend_runs`/`candidates` 두 테이블만(evidence_lines/
  regions/exclusions은 근거 조립·지역확인·재시도 세션이 추가할 몫이라 만들지 않음).
- **`alembic/versions/0003_recommend_runs_candidates.py` (신규)** + `alembic/env.py`에
  `import recommend.models` 추가.
- **`recommend/core.py` (신규)** — `check_run_ready(run)` 하나. 순수 함수.
- **`recommend/service.py` (신규)** — `load_candidate_with_run`, `link_published_pin`(가드 UPDATE).
- **`recommend/flows.py` (신규)** — `publish_candidate`. 계획 문서 그대로 구현하되 아래 "꼭
  읽어야 할 것"의 이유로 세 군데를 계획과 다르게 구현했다.
- **테스트**: `test_core.py`(순수), `test_service.py`, `test_flows.py`(계획 "검증" 절의 케이스
  전부 — 비구성원/비작성자/NOT_READY/멱등 2연속/동시 게시 레이스/PIN_DUPLICATE 롤백/
  IDEMPOTENCY_CONFLICT 롤백/멱등 경로에서 핀 소실 전파, 총 8개 시나리오 + 순수 함수 테스트).

**검증(실제로 실행 확인, Docker로 PostGIS 띄운 뒤)**:
```
cd backend && ./.venv/Scripts/python.exe -m pytest authz/tests auth/tests common/tests pins/tests recommend/tests -q
```
→ **210 passed, 1 skipped**(pins의 기존 skip). `recommend/tests`만 19 passed. `ruff check`
recommend 소스+테스트 전부 통과(마이그레이션 파일의 `Union`/`Sequence` 스타일 경고는
0001_pins.py/0002_event_log.py에도 이미 있는 기존 컨벤션이라 그대로 따름 — 새로 만든 문제
아님, 확인 완료). `python -c "import main"` 정상.

## 꼭 읽어야 할 것 (계획 문서와 실제 구현이 갈라진 곳)

1. **계획 문서가 전제한 멤버십 인터페이스가 이미 삭제된 상태였다.** `recommend/
   mentor-review-plan.md`(09-11 22:46 작성)의 `flows.py` 초안은 `membership.is_member(map_id,
   user_id) -> bool`을 썼는데, 이건 `pins/ports.py`가 갖고 있던 옛 `MembershipGateway`
   Protocol이다 — pins의 PR #71 재작업(09-12 00:10~00:24, 계획보다 늦게 끝남)이 그 파일에서
   `MembershipGateway`/`EventPublisher`를 통째로 삭제하고 `authz.guard`/`authz.core.can()`
   체계로 옮겼다(`pins/for_Root.md` 참고). 계획이 참조한 인터페이스 자체가 없어져서 그대로
   옮길 수 없었다.
2. **비구성원 실패 코드를 403 FORBIDDEN → 404 NOT_FOUND로 정정.** 계획의 실패 매핑 표는
   "요청자가 구성원 아님 → 403 FORBIDDEN"이라고 썼지만, `docs/permissions.md`("권한을
   어디서 강제하는가" 절, 계약 변경 — 이 역시 계획보다 늦게 확정)는 "비구성원 → 404(존재를
   안 흘림) / 구성원인데 액션 불가 → 403"으로 못박아뒀다. 두 코드 다 있는 게 아니라 이
   문서가 최신 정본이라고 판단해 404로 구현했다.
3. **"후보가 남의 run 소속" 케이스를 AI_PIN_PRIVATE → FORBIDDEN으로 정정(2번보다 판단이
   더 필요했던 부분).** 계획은 이 케이스에 `AI_PIN_PRIVATE`(404)를 썼다. 처음엔 "비공개
   후보니까 존재를 안 흘리는 게 맞다"고 판단해 그대로 구현했는데, **전체 테스트를 같이
   돌려보니 `authz/tests/test_rule_a_static.py::test_only_guard_module_calls_resolve_principal`
   가 실패했다** — 이 테스트는 "`resolve_principal`은 `authz.guard` 밖에서 직접 호출하지
   않는다"(Rule A)를 AST로 강제한다. `AI_PIN_PRIVATE`를 직접 만들려면 `resolve_principal`+
   `can()`을 flows.py에서 직접 불러야 하는데, 그게 Rule A 위반이었다. 그래서
   `authz.guard.require("recommend.publish", loader)`가 돌려주는 의존성 함수를 그대로
   호출하도록(라우터가 아니라 이미 읽은 candidate로 `loaded`를 직접 채워서) 바꿨고, 그
   함수는 "구성원인데 액션 불가 → 403 FORBIDDEN"만 낸다(`docs/permissions.md`의 2값
   체계와도 일치 — 이 문서엔 애초에 AI_PIN_PRIVATE 같은 세 번째 값이 없다). 계획의
   AI_PIN_PRIVATE는 Rule A 확정 전에 쓰인 추측이었다고 결론 내렸다.
   - **루트 확인 필요**: `authz.guard.require()`를 FastAPI 라우트가 아닌 평범한 함수(flows.py)에서
     `Depends` 없이 직접 호출하는 이 방식이 처음 나온 사례다(`authz.core.Resource`/`.obj`를
     흉내낸 작은 `_LoadedCandidate` dataclass로 `loaded=`를 채움). `shortlist`의 핀 확정
     플로우도 같은 모양(멘토 코멘트 1,3 — 게시/확정 둘 다 "flow 함수" 패턴)일 가능성이 커서,
     이 패턴이 맞다면 `authz.guard`에 "loader 없이 loaded를 직접 받는" 변형을 정식으로
     추가하는 게 나을 수도 있다 — 지금은 `require()`의 클로저를 그대로 재사용하는 임시방편이다.
4. **`pins.api.create_ai_pin`의 이벤트 타입 버그(pins 소관, 이 세션은 우회만 함).**
   `create_ai_pin`이 반환하는 `mutation.event`는 `pins.core.pin_created_event(pin)`이 만든
   것이라 `type="pin.created"`다. 그런데 `docs/events.md`(전체 채널 표)는 「지도에 올리기」의
   타입을 `"pin.published"`로 이미 못박아뒀고, `create_ai_pin` 자신의 docstring도 "recommend의
   후보 게시 전용"이라고 밝히고 있다 — 이 함수가 만드는 이벤트는 애초에 `pin.published`였어야
   한다. `pins/api.py`는 다른 모듈 소유 파일이라 직접 고치지 않고, `flows.py`에서 payload는
   그대로 두고 `type`만 `pin.published`로 바꿔 새 `Event`를 만들어 기록했다(`flows.py` 모듈
   docstring에 이유 기록). **pins 세션(또는 루트)이 `pins/core.py::pin_created_event` 호출을
   `create_ai_pin` 안에서 `pin.published` 전용으로 바꾸는 게 근본 수정** — 그러면 이 우회
   코드는 지워도 된다.

## data-model.md 대비 스키마 차이 (루트 확인 필요)

`candidates`에 `lat`/`lng`(Float)를 추가했다 — `docs/data-model.md` 144-150행의 candidates
정의엔 없는 컬럼이다. `pins_api.create_ai_pin(lat=..., lng=...)`를 부르려면 좌표가 필요한데
`places` 모듈이 아직 비어 있어(온디맨드 조회 불가) 후보 생성 시점에 좌표를 직접 들고 있는
수밖에 없었다 — `pins` 테이블이 `place_id`와 별개로 자기 `geom`을 갖는 것과 같은 이유
(차원 압축, architecture.md 3층 모델). `region_id`도 `regions` 테이블이 아직 없어 FK 없이
컬럼만 뒀다. **data-model.md에 이 두 컬럼을 반영할지, 아니면 후속 세션(근거 조립/후보 생성
파이프라인)이 실제로 값을 채울 때 재검토할지는 루트 결정이 필요하다.**

## 가볍게 훑거나 생략해도 되는 것

- `router.py`/`main.py` 등록 — 이 계획 문서는 `flows.py` 자체만 다루고 라우터를 언급하지
  않는다. `recommend/CLAUDE.md`의 나머지 책임(run 생성, 근거 조립, 실격 필터, 선호 순위,
  반경 넓히기/재시도, funnel)은 이번 범위 밖 — `docs/api-spec.yaml`의 `recommend` 태그
  엔드포인트 대부분이 아직 없다.
- `evidence_lines`/`regions`/`exclusions` 테이블 — 후속 세션 몫.
- `core.check_run_ready`가 `done`이 아닌 모든 상태(collecting_evidence/awaiting_region_confirm/
  executing/failed)를 동일하게 `NOT_READY`로 묶는다 — `failed`를 별도 코드로 구분할지는
  결정 이슈로 남겨둠(아래).

## 루트 확인·결정 필요 (모아서)

1. **위 "꼭 읽어야 할 것" 3번** — `authz.guard.require()`를 non-FastAPI 함수에서 `Depends`
   없이 직접 호출하는 패턴이 정식 지원 대상인지, 아니면 `authz.guard`에 별도 진입점을
   추가해야 하는지. `shortlist`도 같은 패턴이 필요할 가능성이 커서 이번에 정리하면 좋다.
2. **4번(pins.api 이벤트 타입 버그)** — `pins` 세션이 근본 수정할 항목으로 전달 필요.
3. **candidates.lat/lng 스키마 차이** — data-model.md 반영 여부.
4. **`check_run_ready`의 `failed` 처리** — NOT_READY로 뭉뚱그릴지, 별도 코드/화면이
   필요한지(`RECOMMEND_FAILED`는 파이프라인 실행 중 실패를 위한 코드라 이미 완료된 실패
   run을 게시 시도하는 경우와는 다른 상황).
5. (이관) **pins/for_Root.md가 남긴 "create_ai_pin의 Principal 구성"** — 이번엔 실제로
   `Principal`을 만들 필요가 없어(3번 항목 참고, authz.guard.require가 알아서 처리) 이
   결정은 여전히 미룰 수 있었다 — 참고로만 남김.

## #659 (2026-10-20)

- llm 프롬프트에 카페 예시 있음: `llm/prompts.py:42` serves_alcohol 설명의 "카페인데 맥주도 되는 곳". 이번 PR에서는 건드리지 않았다.

## #681-3 (2026-10-24)

- (해결) 표에 없는 카페 `pet_friendly`·`accessible`·`vegetarian_friendly`와 관광지 `pet_friendly`는 루트 답변대로 '쓰지 않음'으로 표에 넣었다. 그 밖에 표에 없는 키는 '쓴다'다. 표 정의는 `constraints.HEART_SIGNAL_BY_CATEGORY`.
- `is_place_identity_key`(원함이어도 required 내리기, #422)는 음식점만 센다. 카페 `bakery`·관광지 정체 키로 번지지 않게 막았다.

## #681-4·#681-12 (2026-10-24)

- **#681-4 (구현함)**: 카드 checks는 hard + 🚫 사유로 낸 soft 키는 모름·거짓도 그대로, 나머지 선호(soft)는 충족한(known+passed) 것만 점수 기여 큰 순 최대 5줄(`core.limit_preference_checks`). 점수·집계·이유 입력은 전체 체크 그대로다.
- **「외 N개」는 못 했다**: Check 응답에 줄 수를 담을 칸이 없다(스키마를 바꾸지 말라는 지시). 필요하면 응답에 `hidden_preference_count` 같은 칸을 루트가 스펙에 넣어 주면 `limit_preference_checks`가 넘긴 개수를 채운다. 또 이 변경으로 원한 선호가 모름이어도 「확인 필요」로 안 보인다(기존 테스트 2건 기대값을 바꿨다).
- **#681-12 (보류, 루트 확인 필요)**: `places.schemas.PlaceInfo`에 `curated`가 없다(`source`는 "permit" | "tourapi"뿐). 정예 장소를 "정예 조사"로 표시하려면 places가 `PlaceInfo.curated: bool`(또는 `source="curated"`)을 주고 `PlaceSourceInfo` 스펙에도 값이 있어야 한다. 그 뒤 recommend가 `place_source`에 그대로 싣는다 — recommend 쪽 변경은 그때 몇 줄이다.

## #690 is_open (2026-10-24)

- 요일 단위 휴무 판정은 `places.core.is_open_on`을 import하지 않고 `recommend.core.trip_open_status`에 같은 규칙으로 구현했다(hours의 빈 요일, `closed_days`, 전날 구간이 24:00을 넘겨 이어지는 새벽은 영업). 공개 래퍼는 필요 없다.
- `PlaceFactsGateway`에 선택 메서드 `get_hours`를 더했다(실제 모드는 `places.api.get_hours`). 이 메서드가 없는 게이트웨이(dev·다른 모듈 테스트의 가짜)는 전부 「모름」(통과 + 확인 필요)이다.
- 확인 필요 기준: 휴무가 아닌 요일 중 영업이 확인된 요일(hours에 구간이 있는 요일)이 하나도 없으면 `needs_check`다. 즉 행이 없는 경우뿐 아니라 `closed_days`만 있고 여행 요일이 거기 없는 경우(휴무는 아니지만 영업 여부는 모름)도 확인 필요로 둔다 — 문서 「영업 중 판정」의 `unknown` 정의를 따랐다.
- known 통과 체크의 문구는 「여행 기간에 영업하는 날이 있음」(`PASSED_LABELS["is_open"]`)이다. 다른 문구를 원하면 알려 달라.

## #720 (2026-10-24)

- EvidenceLine에 `enforced`를 더했다(`fact_key is not None`, 응답에 항상 채움). 구현은 `flows._evidence_response` 한 곳이다. 스펙 PR #725가 정본이며 이견 없음.
