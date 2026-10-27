# 계획 보조 에이전트 모드 v2 구현 명세

- 상태: 설계 확정 (2026-10-02), 개정 (2026-10-15). 수치는 초기값이며 운영 기록을 보고 조정한다.
- 2026-10-27 개정: 품질 점검 기록(21절), 18절 체크 표시를 이슈 상태에 맞춤(#676).
- 2026-10-16 개정: #534 평가 뒤 모델 유형(정체, 갈림) 제안을 노출하고, 신호 순위를 모델에서 코드 규칙으로 옮겼다(7절, #582). 에이전트의 모델 호출은 진단과 추천 막힘 조언 둘이다(요약 문장은 고정 문구, 2026-10-16).
- 2026-10-15 개정: 10/2 이후 바뀐 추천과 다른 모듈 계약을 반영했다. 반응 2종(#360), 안전 조건 폐지(#425), 가격 라벨 삭제(#423), 사유의 방향(#228), 조건별 근거 줄(#419), 칩 코드 처리(#412), llm 공개 함수(#460), 카테고리 정의(#280), 지도 삭제와 탈퇴(#369, #431, #155). 이 개정으로 Stance(모델이 내던 방향)를 없앴고, 조건 완화 조언과 애매한 사유 칸을 다시 정했다(9절, 8절).
- 이름 구분: 기획안 3절의 "에이전트 루프"는 AI 추천 한 번이 도는 단계(⓪~⑤)를 가리킨다. 이 문서의 "계획 보조 에이전트"는 그와 다른 기능이다.
- 읽는 사람: 이 기능을 구현하는 Claude Code 세션, AI 담당, FE 담당
- 담당: 프론트엔드는 FE 담당. 나머지(backend/agent, 다른 모듈 api.py 추가와 연결, llm 프롬프트, 평가셋, 인프라)는 AI 담당이 백엔드까지 함께 맡는다(2026-10-15, 백엔드와 AI 경계가 모호해서). FE는 v1 화면 일이 먼저이고, v2 구현이 진행되면 바뀐 계약을 알려 중간에 화면을 붙인다
- `backend/agent/CLAUDE.md`와 `frontend/src/features/agent/`의 작업 세션은 이 문서를 먼저 읽는다.
- 계약은 정본 문서에 반영돼 있다(#510): `docs/api-spec.yaml`(agent 태그), `docs/events.md`(agent 이벤트 4종), `docs/data-model.md`(agent 절), `docs/permissions.md`, `docs/errors.md`. 이 문서와 정본이 다르면 정본을 따르고 루트에 보고한다.
- 모델 호출 추가는 명세대로 진행하기로 결정했다(#509, 2026-10-15). 루트 CLAUDE.md "모델 호출" 절에 반영돼 있다.
- "초안"이 붙은 항목은 구현하면서 바뀔 수 있다. 나머지는 팀 결정이다.

## 0. 먼저 읽을 문서

1. `/CLAUDE.md`: 절대 원칙, 용어
2. `backend/CLAUDE.md`: 백엔드 공통 컨벤션
3. `docs/architecture.md` 1.1(flow와 동시성), 1.3(상주 상태), 1.4(지도 삭제와 정리)
4. `docs/data-model.md` common 절(event_log), `docs/events.md`: 전달 보장, seq 구멍(4번)
5. `docs/constraints.md`: fact_key, unknown_policy, 사유의 방향(`wants`), 반대 사유 칩
6. `docs/permissions.md`: 비구성원 404, 구성원이지만 불가 403, 근거 줄 빼기는 쓴 사람만
7. `backend/llm/CLAUDE.md`, `backend/recommend/CLAUDE.md`
8. `backend/common/categories.py`: 카테고리 목록과 카테고리마다 할 수 있는 것

루트 `CLAUDE.md`의 "모델 호출" 절은 v1 기준이다("v1 요청 중 모델 호출은 ② 하나", gpt-6-luna, #372). 같은 절이 "모델 변경은 결정 이슈를 먼저 연다"고 정하고 있으므로, v2 에이전트 호출 4종(우선순위, 진단, 요약, 추천 막힘 조언)은 #509에서 결정했고 루트 CLAUDE.md, `backend/llm/CLAUDE.md`, 기획안 8절에 반영했다. 그래도 단계는 지킨다: M0은 모델 없이 shadow로 돌고, llm 쪽 agent 함수는 M1에서 고정 응답 스텁으로 먼저 통합한 뒤 실제 모델로 바꾼다.

## 1. 무엇을 만드는가

계획 보조 에이전트는 지도 상태를 주기적으로 관찰해 결정이 막힌 지점을 찾고, 다음 행동을 제안한다. 에이전트는 아무것도 직접 실행하지 않는다. 사람이 누를 버튼만 내놓는다.

산출물은 세 가지다.

1. 지도 제안: 지도 탭 좌측 하단 "핑고 AI 조언" 버튼을 누르면 열리는 바텀시트의 제안. 지도당 동시에 1개.
2. 우리 조건 요약: 같은 바텀시트에 항상 있는 카테고리별 사유와 선호 요약.
3. 추천 막힘 조언: AI 추천 결과 화면에 붙는 메시지. run 요청자만 본다.

범위 결정:

- 모드는 지도 단위다. 기본값 on, 구성원 누구나 켜고 끈다.
- 지도 제안은 전체 공개만 있다. 개인 채널 제안은 없다.
- 여행 `end_date` 다음 날부터 관찰하지 않는다.
- 새 지도 제안이 있으면 버튼에 작은 점을 붙인다. 점은 사용자별로, 그 제안을 아직 열람하지 않았을 때만 보인다. 요약 갱신에는 점을 붙이지 않는다.
- 배너 문구는 띄우지 않는다.

## 2. 넘지 말 것

1. agent 모듈은 다른 모듈의 테이블에 쓰지 않는다. 다른 모듈 데이터는 `<module>/api.py`로만 읽는다(#113). 다른 모듈의 `models.py`, `service.py` import 금지.
2. **스냅샷, 도구 결과, 모델 입력에 비공개 데이터를 넣지 않는다.** 비공개 데이터는 run, 후보(candidates), run의 근거 줄(evidence_lines), 제외 목록(exclusions)이다. v1 핀은 항상 public이고 visibility로 분기하지 않는다(#273). 비공개 AI 후보는 핀이 아니라 후보 행이다. run 존재 여부는 정체 전제 판정(6.2)에만 bool로 쓰고, 모델 입력과 문구에는 넣지 않는다. 예외는 추천 막힘 조언 하나로, 그 run의 요청자에게 그 run의 데이터만 쓴다.
3. 모델이 쓴 숫자와 인용을 그대로 화면에 내지 않는다. 검증을 통과한 claim의 값으로 서버가 렌더한다(11절).
4. 행동 목록에 확정, 삭제, 반응 변경, 근거 줄 빼기는 없다. 버튼은 사람이 원래 하던 동작으로만 이어진다(16절). 조건을 완화하는 것은 사람이다(가드레일 4). 에이전트는 "이 조건 때문에 몇 곳이 빠졌다"까지만 말한다.
5. 알러지 같은 안전 조건은 서비스가 판단하지 않는다(#425, 가드레일 8). 에이전트도 알러지 사유를 조건으로 해석하거나 구체화를 요청하지 않고, 가게에 직접 확인하라는 고정 안내만 낸다(8절).
6. 모델 호출 중에는 DB 세션을 열어두지 않는다(12.6).
7. 프롬프트와 모델 왕복은 `backend/llm`에 둔다. 다른 모듈은 `llm/api.py`만 가져다 쓴다(#460). agent는 llm 함수에 요청만 보낸다. 실제 모델을 쓸지 고정 응답 스텁을 쓸지는 llm이 아니라 받는 쪽인 `agent/deps.py`의 Gateway가 고른다(recommend/deps.py와 같은 방식). 도구 실행은 agent가 llm에 넘기는 콜백으로 한다.
8. `docs/events.md`에 없는 이벤트 타입을 쓰지 않는다. 15절의 4종은 반영돼 있다(#510).
9. `docs/constraints.md`의 값을 바꾸거나 새 fact_key를 만들지 않는다.
10. 모델 출력 검증이 실패하면 재요청하지 않고 침묵한다.
11. 제안과 요약 문구에 구성원 이름을 쓰지 않는다. 모델에는 이름 대신 관찰 단위 별칭(m1, m2 …)을 준다. 실격 사유는 개수로만 보여준다. 알러지 사유는 원문을 인용하지 않는다.
12. 사유의 키와 방향을 정하는 곳은 ② 하나다. 에이전트 모델은 키나 방향을 따로 내지 않고, ② 결과를 claim으로 가리키기만 한다(8.1).
13. **agent 테이블에는 사유 원문을 저장하지 않는다**(2026-10-15 결정). 사유는 `reaction_id`로만 가리키고, 원문이 필요한 문장은 응답과 이벤트를 만들 때 pins에서 읽어 렌더한다. 반응이 지워지면(탈퇴 #155, 지도 나가기 #369, 반응 삭제) 그 인용은 저절로 사라진다. 탈퇴할 때 agent에서 지울 곳을 계속 늘리지 않기 위한 원칙이다. 12.9, 13절 참고.
14. llm 품질을 기다리지 않는다. 스키마에 맞는 고정 응답 스텁으로 오케스트레이션, API, 이벤트를 먼저 통합한다(recommend 모듈과 같은 관례).

## 3. 용어

- 관찰: 지도 하나에 대해 스냅샷 읽기, 탐지, 정책, 필요하면 모델 호출, 저장까지 하는 한 번의 처리. `agent_runs` 한 행.
- 신호(Signal): 탐지기가 낸 개입 후보. 유형, 카테고리, 근거 id, 특징값을 가진다.
- 지도 제안(suggestion): 신호가 정책과 검증을 통과해 저장된 것. `agent_suggestions` 한 행.
- 모델 유형: 모델이 진단하는 유형(stall, split). 코드 유형: 템플릿으로 만드는 유형(no_reaction, category_gap).
- 모델 사용 1회: 모델(진단)을 부른 관찰 1회. 우선순위는 코드 규칙이라 세지 않는다(#582). 요약 갱신은 별도 1회다. 추천 막힘 조언은 지도 상한에 세지 않는다.
- fingerprint: 중복 금지용 해시. 유형 + 카테고리 + 정렬된 근거 id.
- evidence_hash: 상태 재확인용 해시. 근거 id + 반응 종류 + updated_at.
- 기준 시간: 정체, 갈림, 반응 공백의 시간 조건에 쓰는 지도별 시간(6.1).
- 커서: 지도별로 확인한 event_log seq. lease: 지금 관찰 중임을 나타내는 자리표.
- 열람: 사용자가 바텀시트를 열어 활성 제안이 화면에 보인 것.
- 근거 줄: AI 추천의 근거 확인 화면에 보이는 사유 한 줄(evidence_lines 한 행). 사유 글 하나에 조건이 여럿이면 줄이 여럿이다(#419).
- 실격 조건: 🚫 사유에서 나와 라벨과 어긋나는 가게를 후보에서 빼는 근거 줄(배지 required). ♥나 「+」에서 나온 선호 줄(배지 preferred)은 점수만 바꾸고 후보를 빼지 않는다.
- 방향(`wants`): 그 특징이 있는 곳을 원하는지(true) 피하는지(false). ②가 키와 함께 낸다(#228).
- 키 없는 사유: ②가 키를 붙이지 못했거나, 일부러 키를 두지 않은 사유(알러지 #425, 칩 「비싸요」 #423).

## 4. 파일 구조

```
backend/agent/
  CLAUDE.md             # 이 문서를 먼저 읽으라고 가리킨다
  constants.py          # 5절의 초기값
  priority_policy.yaml  # 우선순위 정책 (7절). 변경은 PR + PM 승인
  models.py             # agent_* 테이블 (13절)
  schemas.py            # API 스키마, 모델 출력 스키마 (11절)
  core.py               # 탐지기, 기준 시간, 정책, 출력 검증, 렌더 (순수 함수, DB를 모른다)
  snapshot.py           # 다른 모듈 api.py로 스냅샷 조립 (읽기 전용)
  tools.py              # 모델 도구 (10절)
  service.py            # agent_* 테이블 읽기와 쓰기
  flows.py              # run_tick, observe_map, update_summary, advise_run (순서와 실패 처리만)
  deps.py               # Gateway: llm 호출(실제 모델 또는 고정 응답 스텁), 다른 모듈 읽기
  api.py                # 다른 모듈에 여는 함수: advise_run, purge_map_data, delete_by_user
  router.py             # 14절 엔드포인트 (agent 태그)
  tests/
backend/llm/            # agent_diagnose 추가(agent_advise_run은 #749에서 지움). llm/api.py에서 연다(agent_prioritize는 #582에서 지움, 요약은 고정 문구라 모델 함수 없음)
backend/recommend/      # api.py에 run 조회와 시뮬레이션 함수, 근거 줄 분류 함수 공개. GET /runs/{runId}/advice
backend/pins/           # api.py에 반응 표 조회 함수 추가. 사유 조회는 기존 list_reasoned_reactions를 쓴다
frontend/src/features/agent/   # 버튼, 바텀시트, 이벤트 처리
```

카테고리 목록은 `common/categories.py`에서 꺼낸다(#280). agent 안에 카테고리 이름을 따로 적지 않는다.

flow 함수에는 판단을 두지 않는다. `if`가 늘어나면 그 분기는 `core.py`로 옮긴다(architecture.md 1.1).

## 5. 상수 초기값

```python
# backend/agent/constants.py  (초기값. 조정 기준은 20절)
from datetime import timedelta

TICK_INTERVAL_SEC = 300            # tick 주기
LEASE_SEC = 180                    # 관찰 lease
TICK_MAX_MAPS = 6                  # tick당 처리 지도 수. 관찰 최악 약 16초(#534) × 10이 lease 180초에 가까워 6으로(#582)
TICK_BUDGET_SEC = LEASE_SEC - 30   # 150초. 시작 뒤 이만큼 지나면 남은 지도는 관찰하지 않고 lease만 푼다(#677, #754)
ERROR_RETRY_DELAYS = (timedelta(minutes=30), timedelta(hours=2), timedelta(hours=6))   # 관찰이 연속 1, 2, 3회 이상 예외로 끝난 지도를 다시 보는 간격(#677, 초안)
SHADOW_DIAGNOSES = ()              # 이 유형의 제안은 저장만 하고 내보내지 않는다. 코드 유형은 #531, 모델 유형은 #582부터 노출(#534 평가)
AGENT_LOOP_IN_PROCESS = settings.agent_loop_in_process   # 환경 변수 AGENT_LOOP_IN_PROCESS=1로 켠다. 기본 꺼짐 (12.1)

PER_MEMBER_DAILY_MODEL_USES = 4    # 개인 단위 값. 지도 상한 = 구성원 수 × 이 값
DAY_BOUNDARY_TZ = "Asia/Seoul"     # 하루 = KST 자정에 초기화

STALL_ACTIVE_MEMBERS = 2           # 정체 활동 기준
TIME_MULTIPLIER = 3                # 기준 시간 = 리듬 × 배수 × D-day 계수
TIME_MIN = timedelta(hours=1)
TIME_MAX = timedelta(hours=12)
RHYTHM_WINDOW_EVENTS = 20          # 최근 이벤트 20개의 간격 중앙값
RHYTHM_MIN_EVENTS = 6              # 이보다 적으면 기본값
RHYTHM_DEFAULT_BASE = timedelta(hours=3)   # "리듬 × 배수" 자리에 들어간다
DDAY_FAR, DDAY_MID = 15, 4         # D-15 이상 1.0, D-4 이상 0.5, 그 외(여행 중 포함) 0.25
DDAY_FACTOR_FAR, DDAY_FACTOR_MID, DDAY_FACTOR_NEAR = 1.0, 0.5, 0.25

NO_REACTION_MIN_TARGET_PINS = 3
NO_REACTION_UNSEEN_RATIO = 0.5
NO_REACTION_DAILY_LIMIT = 1        # 지도당

CATEGORY_GAP_MIN_CONFIRMED = 2

SUMMARY_NEW_REASONS = 3

BLOCKED_RUN_MAX_RESULTS = 3        # 결과가 이 값 미만이면 추천 막힘
BLOCKED_RUN_MIN_SAME_CATEGORY_RUNS = 3   # 또는 같은 사람이 같은 카테고리 run을 이 값 이상 만들었으면 (초안)
# 재시도 상한(attempt_no)은 개인 단위, 카테고리 무관, 10회다(#31, 2026-10-15 5→10회). attempt_no로 세면 다른 카테고리 시도가 섞인다. 그래서 같은 카테고리 run 수를 따로 센다(GET /maps/{mapId}/runs의 기록, #469).

# 진단 도구 상한(1회당 5회, structure_reasons 1회)은 llm이 강제한다(llm.prompts, #532). agent 상수에서는 지웠다(#533)
TOOL_RESULT_MAX_ITEMS = 30         # 초안

BACKOFF_HOURS = (2, 6, 24)         # 연속 닫힘 1회, 2회, 3회 이상
SUGGESTION_TTL = timedelta(hours=24)
AGENT_RUNS_RETENTION_DAYS = 30

MODEL_TYPES = ("stall", "split")
CODE_TYPES = ("no_reaction", "category_gap")

# 요약의 키 없는 사유 나누기 (8절). 값은 docs/constraints.md 칩 표를 따른다
NOT_FILTERED_CHIP_IDS = ("food_expensive", "cafe_expensive", "sight_expensive")   # 가격 키 없음 (#423)
SAFETY_WORDS = ("알러지", "알레르기")   # 초안. 이 낱말이 든 글은 "추천이 거르지 않아요" 칸으로
```

카테고리는 상수로 두지 않고 `common/categories.py`에서 꺼낸다.

- 관찰 대상 카테고리 = `categories.pinnable()` (지금 음식점, 카페, 관광지). 숙소와 기타는 v1에서 핀을 만들 수 없어(#281) 공백 탐지에 넣으면 영원히 공백으로 나온다.
- 추천 대상 카테고리 = `categories.recommendable()` (#145).
- 숙소가 핀으로 다시 생기면(v2) 이 목록에 자동으로 들어온다. 그때 숙소 관련 분기(6.2, 6.5)를 다시 확인한다.

## 6. 지도 제안 유형과 탐지 규칙

탐지는 네 유형 모두 `core.py`의 순수 함수가 한다. 입력은 스냅샷과 현재 시각, 출력은 `list[Signal]`이다.

| diagnosis | 이름 | 제안 내용 작성 | 허용 행동 |
| --- | --- | --- | --- |
| stall | 반대 후 정체 | 모델 진단 | open_recommend, search_place, show_pins |
| split | 의견 갈림 | 모델 진단 | open_recommend, show_pins |
| no_reaction | 반응 공백 | 템플릿 | show_pins |
| category_gap | 카테고리 공백 | 템플릿 | open_recommend, search_place, show_pins |

```python
@dataclass(frozen=True)
class Signal:
    id: str                          # 관찰 안에서의 식별자: s1, s2 ...
    diagnosis: Literal["stall", "split", "no_reaction", "category_gap"]
    category: str | None
    pin_id: str | None               # split만 사용
    evidence_ids: tuple[str, ...]    # 정렬된 reaction_id 또는 pin_id
    features: dict                   # 우선순위 입력 (7절)
    fingerprint: str                 # hash(diagnosis, category, evidence_ids)
    evidence_hash: str               # hash(evidence_ids와 각 항목의 type, updated_at)
```

스냅샷의 "행동"은 세 가지다: 반응 등록과 수정(reactions.updated_at, user_id), 핀 생성(pins.created_at, created_by), 확정 추가(shortlist_items.added_at, added_by). 모두 삭제되지 않은 핀 기준이고, 각 행동에는 그 핀의 카테고리가 붙는다. 핀 분류는 찍은 사람이 고칠 수 있으므로(#466) 스냅샷은 지금 분류를 쓴다.

반응은 ♥(like)와 🚫(against) 두 가지다(#360). "?" 미확인은 반응 행이 없는 것으로 표현한다. 실시간 핀(`source=live`, #382)은 자체 DB 장소가 없어 장소 이름과 라벨이 없다. 문구에 핀 이름을 쓸 때 실시간 핀은 사용자가 친 검색어(`search_query`)를 쓴다.

### 6.1 기준 시간

```python
def time_threshold(action_times: list[datetime], start_date: date, today: date) -> timedelta:
    return clamp(rhythm_base(action_times) * dday_factor(start_date, today), TIME_MIN, TIME_MAX)

def rhythm_base(action_times: list[datetime]) -> timedelta:
    recent = sorted(action_times)[-RHYTHM_WINDOW_EVENTS:]
    if len(recent) < RHYTHM_MIN_EVENTS:
        return RHYTHM_DEFAULT_BASE              # 배수를 곱하지 않는다
    gaps = [b - a for a, b in zip(recent, recent[1:])]
    return median(gaps) * TIME_MULTIPLIER

def dday_factor(start_date: date, today: date) -> float:
    d = (start_date - today).days               # 여행 중이면 0 이하
    if d >= DDAY_FAR:
        return DDAY_FACTOR_FAR
    if d >= DDAY_MID:
        return DDAY_FACTOR_MID
    return DDAY_FACTOR_NEAR
```

리듬 계산에는 event_log가 아니라 도메인 테이블의 시각을 쓴다. event_log는 24시간만 보존된다. today는 KST 기준 날짜다.

### 6.2 반대 후 정체 (stall)

공통 전제를 모두 만족하고, 활동 기준과 시간 기준 중 하나라도 걸리면 신호다.

```python
def detect_stall(s: Snapshot, now: datetime, th: timedelta) -> list[Signal]:
    out = []
    for c in categories.pinnable():
        againsts = [r for r in s.reactions if r.type == "against" and s.pin(r.pin_id).category == c]
        if not againsts:
            continue
        t0 = max(r.updated_at for r in againsts)
        # 공통 전제
        if any(p.category == c and p.created_at > t0 for p in s.pins):
            continue
        if s.has_run_since(c, t0):          # bool만. 모델 입력과 문구에 넣지 않는다
            continue
        if any(s.pin(i.pin_id).category == c for i in s.shortlist):
            continue
        # 활동 기준 또는 시간 기준
        actors = {a.user_id for a in s.actions if a.at > t0 and a.category != c}
        by_activity = len(actors) >= STALL_ACTIVE_MEMBERS
        by_time = now - t0 >= th
        if by_activity or by_time:
            out.append(make_signal("stall", category=c, evidence=againsts,
                                   trigger="activity" if by_activity else "time"))
    return out
```

모델은 반대 사유를 읽고 다음 행동을 고른다. 추천 준비 판정(⓪)을 통과하고 C가 추천 대상이면 open_recommend, ⓪를 통과하지 못하면 search_place, 사유가 모호하면 그 핀을 보여주는 show_pins다. ⓪는 "♥나 🚫 의견이 달린 핀이 1개 이상"이라(#360) 반대가 있는 카테고리는 대부분 통과한다. 통과하지 못하는 것은 반대가 달린 핀이 모두 삭제된 경우 정도다.

### 6.3 의견 갈림 (split)

```python
def detect_split(s: Snapshot, now: datetime, th: timedelta) -> list[Signal]:
    out = []
    for p in s.pins:
        if s.is_confirmed(p.id):
            continue
        rs = s.reactions_of(p.id)               # ♥, 🚫 두 가지뿐 (#360)
        like = sum(r.type == "like" for r in rs)
        against = sum(r.type == "against" for r in rs)
        trigger = None
        if like >= 1 and against >= 1 and like >= against:
            if len(rs) == s.member_count:
                trigger = "all_responded"
            elif now - max(r.updated_at for r in rs) >= th:
                trigger = "time"
        if trigger:
            out.append(make_signal("split", category=p.category, pin_id=p.id, evidence=rs, trigger=trigger))
    return out
```

충돌 종류는 코드가 정한다. `compare_reasons`가 ②의 결과(키와 방향)로 ♥ 쪽 사유와 🚫 쪽 사유를 키별로 모으고, 아래 규칙으로 나눈다.

| 종류 | 뜻 | 예 |
| --- | --- | --- |
| same_axis | 같은 특징을 두고 방향이 반대다 | ♥ "조용해서 좋아요"(quiet, 원함) / 🚫 "너무 조용해서 심심해요"(quiet, 피함) |
| different_axes | 서로 다른 특징을 말한다 | ♥ "분위기 좋아요"(키 없음) / 🚫 "주차가 안 돼요"(parking_available, 원함) |
| unclear | 한쪽이라도 키 있는 사유가 없다 | 🚫 칩 「취향이 아니에요」만 있음 |
| unclear | 같은 키에 같은 방향이다(#533) | ♥ "조용해서 좋아요"(quiet 원함) / 🚫 칩 「시끄러워요」(quiet 원함). 취향이 갈린 게 아니라 이 가게가 조용한지를 두고 갈렸다 |

방향이 없는(wants=null) 줄은 키 있는 사유로 세지만 원함, 피함 어느 쪽에도 넣지 않는다. split 진단 입력의 비교 결과는 모델을 부르기 전에 코드가 계산한다(② 호출 포함, 도구 기록과 상한에 세지 않는다). ②가 실패하면 비교 결과 없이 진단한다.

10/2 판에서는 모델이 방향(Stance)과 충돌 종류를 직접 냈다. ②가 방향을 내게 되면서(#228) 같은 계산을 코드로 할 수 있게 됐고, 루트 원칙("새 기능은 먼저 코드로 되는지 묻는다")에 따라 코드로 옮겼다. 모델은 충돌 종류를 받아 조언 문장과 행동만 고른다. different_axes면 양쪽을 만족하는 조건 조합을 조언에 넣고 open_recommend로 잇는다. 화면에는 이름 대신 "♥ 쪽 / 🚫 쪽"으로 표시한다.

**진단 입력(`core.diagnosis_input`, #533, #534).** 모델이 알려고 도구를 한 번 더 부르지 않게, 공개 데이터 몇 칸을 처음부터 넣는다. 사유 글은 넣지 않고 도구(get_reasons)로만 읽게 한다.

- 공통: signal_id, diagnosis
- stall: category, against_pin_ids(🚫가 달린 핀. show_pins 버튼의 근거)
- split: pin_id, place_id(실시간 핀은 null. get_place_facts용), counts({like, against}. 필수 claim 값), 비교 결과(compare_reasons, 6.3)

### 6.4 반응 공백 (no_reaction)

```python
def detect_no_reaction(s: Snapshot, now: datetime, th: timedelta) -> list[Signal]:
    unseen_all: set[str] = set()
    for m in s.members:
        targets = [p for p in s.pins
                   if p.created_by != m.user_id
                   and now - max(p.created_at, m.joined_at) >= th]
        if len(targets) < NO_REACTION_MIN_TARGET_PINS:
            continue
        unseen = [p for p in targets if not s.has_reaction(m.user_id, p.id)]
        if len(unseen) / len(targets) >= NO_REACTION_UNSEEN_RATIO:
            unseen_all |= {p.id for p in unseen}
    if not unseen_all:
        return []
    return [make_signal("no_reaction", category=None, evidence_pin_ids=sorted(unseen_all))]
```

템플릿: 제목 "아직 확인되지 않은 핀이 {n}개 있어요", 확인된 것은 핀 이름 목록, 버튼 "미확인 핀 보기"(show_pins). 누가 확인하지 않았는지는 쓰지 않는다. 지도당 하루 1회까지 낸다.

### 6.5 카테고리 공백 (category_gap)

```python
def detect_category_gap(s: Snapshot) -> list[Signal]:
    if len(s.shortlist) < CATEGORY_GAP_MIN_CONFIRMED:
        return []
    out = []
    for c in categories.pinnable():          # v1: 음식점, 카페, 관광지 (5절)
        if c == "숙소" and s.map.end_date == s.map.start_date:
            continue                         # 숙소가 다시 생기면(v2): 당일치기는 숙소 공백을 보지 않는다
        if not any(s.pin(i.pin_id).category == c for i in s.shortlist):
            out.append(make_signal("category_gap", category=c,
                                   evidence_pin_ids=sorted(i.pin_id for i in s.shortlist)))
    return out
```

템플릿: 제목 "확정 리스트에 {category}가 아직 없어요", 확인된 것 "확정 {n}곳 중 {category} 0곳". 버튼은 추천 대상 카테고리면 "{category} 추천 받기"(open_recommend)와 "{category} 핀 보기"(show_pins), 추천 대상이 아니면 "{category} 검색"(search_place)과 "{category} 핀 보기"다. v1에서는 관찰 대상이 모두 추천 대상이라 뒤의 경우는 숙소가 다시 생길 때 쓴다. 출발일 조건은 두지 않는다.

## 7. 우선순위

정책 사전 검사(12.3)를 통과한 신호가 2개 이상이면 **코드 규칙**이 순위를 정한다(2026-10-16 개정, #582). 1순위 신호 하나만 다음 단계로 간다. 나머지는 버리고, 다음 관찰에서 다시 탐지된다.

10/2 판은 모델(agent_prioritize)이 순위를 정하고 코드가 보정했다. #534 평가에서 모델이 기본 순서와 다르게 둔 경우는 모두 아래 규칙 셋(출발 임박, 같은 가중치의 영향 인원, 연속 닫힘) 그대로였다. 그래서 코드로 옮겼다. 관찰당 약 2초와 우선순위 호출 실패 경로가 없어지고, 에이전트의 모델 호출은 진단 하나만 남는다(#509 기록).

```python
# 입력 특징값 (신호마다)
features = {
    "affected_members": int,        # 영향받는 구성원 수
    "elapsed_ratio": float | None,  # 경과 시간 / 기준 시간
    "dday": int,
    "recent_dismissals": int,       # 같은 유형, 같은 카테고리의 연속 닫힘 수
    "trigger": str | None,          # activity | time | all_responded
    "category": str | None,
}

# core.fallback_order(signals, policy) -> final_order
#   1. 출발이 urgent_dday일 이내면 category_gap을 맨 앞으로
#   2. 나머지는 weights 내림차순
#   3. 같은 weight 안에서는 recent_dismissals가 0인 신호 먼저, 그다음 affected_members 내림차순, 그다음 elapsed_ratio 내림차순
#   4. always_first가 있으면 맨 앞으로, 1순위가 never_first면 아닌 첫 신호를 앞으로
```

```yaml
# backend/agent/priority_policy.yaml (version 2, 2026-10-16 PM 승인. 변경은 PR + PM 승인)
version: 2
rules:
  urgent_dday: 3       # 출발이 이 일수 이내면 확정 리스트 공백(category_gap)을 맨 앞으로
  never_first: []      # 1순위가 될 수 없는 diagnosis
  always_first: []     # 있으면 항상 1순위인 diagnosis
weights:               # 기본 정렬 기준
  stall: 3
  split: 3
  category_gap: 2
  no_reaction: 1
```

version 1의 principles(프롬프트용 원칙 3개)는 모델 호출이 없어져 지웠다. 세 원칙은 위 규칙으로 옮겨졌다: 여러 구성원에게 영향을 주는 신호 먼저(affected_members), 출발이 가까우면 확정 리스트 공백 먼저(urgent_dday), 정체와 갈림을 단순 미확인보다 먼저(weights).

`agent_runs.priority`에 final_order, source(single, rules), fingerprints, rule_hits(어느 규칙이 순서를 바꿨는지)를 남긴다.

구현에서 정한 것(#582): rule_hits는 순서를 바꾼 규칙 이름 목록이다(recent_dismissals, affected_members, elapsed_ratio, urgent_dday, always_first, never_first). 적용은 같은 weight 기준 셋(앞 기준이 같을 때만 다음 기준) → urgent_dday → always_first → never_first 차례이고, 맨 앞으로 옮기기는 안정 정렬이라 위 번호 순서와 결과가 같다. urgent_dday는 `dday <= 3`(여행 중 포함)인 category_gap에 걸린다. always_first 유형이 있으면 출발 임박이어도 그 유형이 1순위다.

## 8. 우리 조건 요약

카테고리마다 새 사유가 3개 쌓이거나(`SUMMARY_NEW_REASONS`), 새 구성원이 지도에서 첫 반응을 남기거나, 지난 요약이 본 사유가 사라지면(반응 삭제, 지도 나가기 #369, 사유 지움) 코드가 그 카테고리의 조건 요약을 갱신한다(`core.summary_changes`, #586). 요약 갱신은 모델을 부르지 않아 모델 사용으로 세지 않는다(고정 문구, 2026-10-16). 요약은 바텀시트에 항상 있고 점이나 알림은 없다.

- 사유가 있는 반응: reason_text가 있거나 reason_chip_ids가 비어 있지 않은 반응. `pins.api.list_reasoned_reactions`가 이미 이 기준으로 돌려준다(글과 칩을 따로, #412).
- 삭제된 핀의 사유도 넣는다. 추천이 삭제된 핀의 사유를 계속 쓰므로(#243) 요약도 같은 기준을 따라야 둘이 어긋나지 않는다.
- 새 사유 수: 지금 사유 있는 반응 중 지난 요약이 보지 않은 것. reaction_id 집합으로 센다. 개수 뺄셈은 반응이 지워진 뒤 새 사유를 놓친다(#586).
- 흐름: `flows.update_summary` → 도구(get_reasons, structure_reasons, compare_reasons) → 칸 나누기(코드) → 구체화 요청 문장(고정 문구) → upsert → `agent.summary_updated`. 모델을 부르지 않는다
- 쓰기는 지도 제안과 별도 트랜잭션, 별도 `agent_runs` 행(trigger=summary)이다.
- 모델 사용 상한은 보지 않는다(used_model=false). 한 관찰에서는 카테고리 하나(`core.pick_summary`)만 갱신하고, 남은 카테고리가 있으면 커서를 지금으로 당겨 다음 tick에 이어 간다(#586).

요약은 다섯 칸이다. 칸을 나누는 것은 코드이고, 기준은 ②가 낸 근거 줄(키, 방향, 배지)이다.

| section | 뜻 | 어떤 줄이 들어가나 | 화면 표기 |
| --- | --- | --- | --- |
| must_keep | 지키려는 조건 (실격 조건) | 배지 required이고 추천이 쓰는 줄(recommend가 정한 enforced, #740). #422, #617 규칙으로 선호로 내려간 줄(글의 음식 종류 "원함", 접근성 외 칩의 "원함")은 빼고 common_prefs나 split_prefs로 간다 | "매운맛 전문 제외 (1명)"처럼 개수만 |
| common_prefs | 겹치는 선호 | 배지 preferred이고 같은 키, 같은 방향을 2명 이상이 남긴 줄 | "조용한 곳 원함 (3명)" |
| split_prefs | 서로 갈리는 선호 | 같은 키에 원함과 피함이 함께 있는 줄 | "조용한 곳: 원함 2 / 원하지 않음 1" |
| vague_fixable | 더 적어 주면 반영될 수 있는 사유 | 키 없는 줄 중 아래 not_filtered가 아닌 것, 방향 없는 줄(no_direction) | 칸 이름 "더 적어 주면 반영돼요", 사유 수와 구체화 요청 문장 |
| not_filtered | 추천이 거르지 않는 사유 | 칩 `NOT_FILTERED_CHIP_IDS`, 글에 `SAFETY_WORDS`가 든 줄, 여행 기간 밖 계절 키(off_season), 이 카테고리에 없는 조건(not_for_category) | 칸 이름 "추천이 거르지 않아요", 개수와 고정 안내만 |

키 없는 사유를 두 칸으로 나누는 이유: 알러지 사유에 "구체적으로 적어 주세요"를 붙이면 더 적으면 추천이 걸러 줄 것처럼 오해하게 된다. 이는 서비스가 안전 조건을 판단하지 않는다는 결정(#425)과 어긋난다. 가격 칩도 키가 없어(#423) 다시 적어도 반영되지 않는다.

줄이 추천에 쓰이는지와 안 쓰이는 이유는 recommend가 정하고 에이전트는 다시 판단하지 않는다(#740). 요약은 `recommend.api.evidence_line_uses`로, 추천 막힘 조언은 `get_run_evidence`의 `enforced`, `not_enforced_reason`으로 받는다. 방향 없는 줄은 vague_fixable, 기간 밖 계절 키와 이 카테고리에 없는 조건은 not_filtered다. 아래 규칙은 키 없는 줄(no_key)에만 쓴다.

키 없는 사유를 나누는 규칙은 다음과 같다. 모두 코드가 한다.

1. 칩은 id로 가른다. 「비싸요」 3종(음식점, 카페, 관광지)은 not_filtered다.
2. 글은 낱말로 가른다. "알러지", "알레르기"가 들어 있으면 not_filtered다. 목록에서 놓친 알러지 글은 vague_fixable로 가서 구체화 요청을 받는다. 그래도 추천이 그 사유로 거르는 일은 없어서, 틀렸을 때 생기는 문제는 안내 문구 하나다.
3. 칩 「너무 멀어요」는 vague_fixable이다. 구체화 요청은 "거리 조건은 '숙소에서 걸어서 10분'처럼 적어 주세요"로 한다. 이렇게 쓰면 ②가 반경 값으로 읽는다(5-6-1).
4. 칩 「취향이 아니에요」와 나머지 키 없는 글은 vague_fixable이다.

not_filtered 칸의 고정 안내는 다음 두 가지다. 알러지 사유가 있으면 "알러지 같은 조건은 추천이 거르지 않아요. 가게에 직접 확인해 주세요."를 보여 준다. 추천 결과 화면 안내(#425)와 같은 말이다. 가격 칩이 있으면 "가격은 아직 추천 조건에 없어요."를 보여 준다. 기간 밖 계절 키는 "여행 기간에는 해당하지 않는 조건이라 이번 추천에 쓰지 않아요.", 이 카테고리에 없는 조건은 "이 카테고리에는 없는 조건이라 이번 추천에 쓰지 않아요."를 보여 준다(#740). 두 칸 모두 개수만 보여 주고, 알러지 원문은 인용하지 않는다(2절 11번).

**구체화 요청 문장은 고정 문구다(2026-10-16 결정).** 칸 나누기와 개수 세기가 모두 코드라, 모델이 할 일은 vague_fixable 사유에 붙일 안내 문장 정도만 남았다. 이 안내는 대부분 "더 구체적으로 적어 주세요" 수준이라 미리 써 둔 문장으로 낸다. 예: 일반 "어떤 점이 별로였는지 적어 주시면 추천에 반영돼요", 칩 「너무 멀어요」 "거리 조건은 '숙소에서 걸어서 10분'처럼 적어 주세요". 그래서 요약 갱신은 모델 사용으로 세지 않는다. 사유에 맞춘 문장이 필요한지는 #588에서 실제 기록을 보고 다시 판단한다.

각 칸의 개수는 코드가 reaction_id로 센다. 한 사람이 같은 키를 여러 번 말해도 1명이다. 버튼 "이 조건으로 {category} 추천 받기"(open_recommend)는 추천 대상 카테고리에서만 보인다. 실제 근거 조립은 기존 ②와 근거 확인 단계가 그대로 한다.

### 8.1 사유 구조화와 ②

요약과 충돌 분석에는 키와 방향이 필요하다. 10/2 판에서는 ②가 방향을 내지 않아, 에이전트 모델이 반응마다 방향(Stance)을 따로 내게 했다. 지금은 ②가 키와 방향을 같이 내므로(#228) Stance를 없앴다(2026-10-15 결정).

- `structure_reasons`는 ②를 그대로 부른다. 입력은 반응의 글이고, 반환은 반응 하나당 근거 줄 여러 개(`{fact_key, wants, badge}`)다. 조건이 여럿인 글은 줄이 나뉜다(#419).
- 칩은 ②를 부르지 않는다. `list_reasoned_reactions`가 돌려주는 칩 정보(키, 방향)를 그대로 쓴다(#412).
- ♥ 반응의 글은 배지 preferred, 🚫 반응의 글은 required로 ②에 넣는다. 추천이 근거 줄을 만들 때와 같은 방식이다.
- 🚫 사유 안의 음식 종류 "원함"을 선호로 내리는 규칙(#422)은 `recommend.api.demote_wanted_place_identity`(#564에서 공개)를 그대로 쓴다. agent에 같은 규칙을 다시 쓰지 않는다.
- 추천 run의 근거 줄은 run마다 따로 저장되고 반응 id와 연결돼 있지 않아 그대로 가져다 쓸 수 없다. 그래서 에이전트가 ②를 따로 부르고, (reaction_id, updated_at)으로 결과를 캐시한다.
- ②는 같은 글도 호출마다 결과가 조금 다를 수 있다(이 모델은 temperature=0을 지원하지 않는다). 그래서 추천 run이 읽은 방향과 요약이 읽은 방향이 드물게 다를 수 있다. 캐시를 두면 같은 지도 안에서는 결과가 고정된다.
- 10/2 판의 "② 정확도 20건 확인 후 처리 방식 결정"은 #410, #419 실제 모델 시험으로 대신한다.

## 9. 추천 막힘 조언

결과가 3곳 미만이거나(`BLOCKED_RUN_MAX_RESULTS`) 같은 사람이 같은 카테고리 run을 3회 이상 만든(`BLOCKED_RUN_MIN_SAME_CATEGORY_RUNS`) 완료 run의 결과 화면에, 더 많이 추천받는 방법을 메시지로 보여준다. 지도 제안이 아니라 AI 추천 탭의 기능이다.

같은 카테고리 run 수는 같은 요청자가 같은 지도에서 이 run까지(created_at 이하) 만든 수다(이 run 포함). 나중 run은 세지 않아 한 run의 대상 여부가 뒤에 바뀌지 않는다(`core.same_category_runs`, #587).

- 엔드포인트: `GET /runs/{runId}/advice`, api-spec의 recommend 태그. 코드는 `agent/router.py` → `agent/flows.advise_run`이다(#587). recommend 라우터에 두면 recommend와 agent가 서로를 import하게 돼서 옮겼다. 권한은 `recommend.api.get_run_meta`로 run을 읽어 authz가 판정한다. agent만 recommend.api를 쓰는 한 방향이다.
- 권한: 비구성원 404, run 요청자가 아니면 403.
- 대상이 아니면 204. 저장된 조언이 있으면 그대로 200. 없으면 생성해 저장하고 200.
- run당 1회: `agent_run_advice`에 `INSERT ... ON CONFLICT (run_id) DO NOTHING` 후 저장된 행을 돌려준다. 낼 조언이 없어도(silent) 빈 advice로 저장해 다시 생성하지 않는다.
- 계산이 실패하면 조언 없음(204)으로 삼키지 않고 500(`INTERNAL_ERROR`)이다. agent_runs에 outcome=error 한 행을 남기고 조언 행은 쓰지 않아 다음 요청이 다시 만든다(#750). FE는 500이면 조언 자리를 숨긴다(16.5).
- 세션: 이 엔드포인트는 요청 단위 세션(get_db)을 쓰지 않는다. 조회와 저장을 짧은 세션으로 나눈다. `realtime/dispatcher.py`가 재전송 조회에 SessionLocal을 짧게 쓰는 것과 같은 이유다.
- 모델을 부르지 않는다(2026-10-27 결정, #749). 종류, 버튼, 문장은 agent 코드(`core.advice_simulations`, `core.choose_run_advice`)가 깔때기 숫자, 근거 줄 종류, 시뮬레이션 결과로 정한다(9.1).

조언 종류는 다음과 같다.

| kind | 조건 | 행동 |
| --- | --- | --- |
| radius | funnel 반경 단계 탈락이 많음. simulate_filter로 반경 배율을 바꾼 후보 수를 claim으로 붙인다 | widen_radius |
| soft_relax | 실격 조건이 후보를 많이 걸렀음. 아래 설명 참고 | 본인 줄이면 open_evidence, 남의 줄이면 없음 |
| vague_reason | 근거 중 추천이 쓰지 않는 줄이 있음(키 없는 줄과 방향 없는 줄, 8절의 not_filtered 줄은 빼고 센다, #740). 예시 문장을 함께 낸다 | 본인 줄이면 open_evidence, 남의 줄이면 없음 |
| exhausted | 중복제외 단계 탈락이 많음. 가드레일 6 때문에 완화할 수 없으므로 사실만 안내 | 없음 |

**soft_relax (실격 조건 때문에 많이 빠졌을 때).** 계산 메모(#585): run의 `result_count`는 상위 3곳 선정 뒤의 수라 최대 3이다. "끄면 몇 곳이 더 남는가"는 `simulate_filter`의 before와 after 깔때기에서 「실격 조건 제거」 차이로 본다. before는 다시 계산한 값이라 같은 호출의 before, after끼리만 비교한다.

 10/2 판은 "unknown_policy가 pass인 hard 키"를 기준으로 했다. 지금 hard 키는 `is_crowded_large` 하나뿐이고, 실격 대부분은 🚫 사유에서 나온 취향 키와 방향(#228)이 만든다. 예를 들어 "너무 매워요"는 매운맛 전문(라벨 참)을 빼고, 칩 「휠체어·유모차로 가기 힘들어요」는 접근성이 확인되지 않은 곳(라벨 거짓)을 뺀다. 칩 「좁아요」 같은 원함 칩은 #617부터 선호라 실격을 만들지 않는다. 그래서 기준을 "실격 조건 근거 줄이 후보를 많이 걸렀음"으로 바꿨다(2026-10-15 결정).

- 근거 줄마다 simulate_filter로 "이 줄을 끄면 몇 곳이 더 남는가"를 계산하고, 많이 늘어나는 줄부터 조언한다.
- 근거 줄 빼기(`−`)는 그 줄을 쓴 사람만 할 수 있다(permissions의 `evidence.disable`). 그래서 줄을 쓴 사람이 run 요청자 본인이면 「근거 확인에서 빼 보기」(open_evidence) 버튼을 준다. 다른 구성원이 쓴 줄이면 "「매운 곳 제외」 조건 때문에 14곳이 빠졌어요"라는 사실 문장만 내고 버튼은 주지 않는다. 문장에 그 구성원의 이름은 쓰지 않는다.
- 라벨이 모르는 가게는 "통과 + 확인 필요"라 실격되지 않는다. 그래서 시뮬레이션 숫자는 라벨이 확실한 가게만 센다.
- 조건을 끄는 것은 사람이다(가드레일 4). 에이전트는 몇 곳이 빠졌는지만 알린다.
- 가격 라벨은 없어졌다(#423). 가격 완화 조언은 없다.

### 9.1 종류 고르기는 코드다 (#749, #750)

advise-v4 프롬프트의 「종류 고르기」는 순서가 정해진 절차였다. 모델이 글로 적힌 절차를 따라 하던 것을 코드로 옮겼다(멘토 리뷰 #680).

1. 깔때기의 「반경 밖 제거」, 「실격 조건 제거」, 「이미 제안·거절됨」 중 `ADVICE_CLEAR_DROP`(5, `agent/constants.py`, 루트 결정 값) 이상 빠진 단계를 많은 것부터 본다. 「영업 종료 제거」와 「추천 가능 아님 제거」는 사람이 바꿀 수 없어 보지 않는다.
2. 반경: 버튼 한 번의 배율로 시뮬레이션해 1곳 이상 늘면 radius. 이미 상한이면 다음 단계. 실격 조건: 켜진 조건 줄을 많아야 세 줄(`ADVICE_MAX_RELAX_LINES`) 하나씩 꺼 봐서 늘면 soft_relax. 이미 제안·거절됨: exhausted(시뮬레이션 없음).
3. 고른 종류가 없으면 vague 줄이 있을 때 vague_reason, 없으면 silent(204).
4. 필요한 시뮬레이션을 먼저 모두 고르고 부른다. 서로 기다리지 않는다. 근거 글은 절차에 들어가지 않아(줄 id, 본인 여부, 종류, 이름만) 글 속 지시가 결과를 바꿀 수 없다.
5. 문장은 고정 문구다. 숫자와 조건 이름은 claim 조각(#717)이다. radius "반경 넓히기를 한 번 누르면 {gained}곳이 더 남아요.", soft_relax "「{label}」 조건을 빼면 {gained}곳이 더 남아요."(본인 줄에만 open_evidence), vague_reason "조건으로 읽지 못한 글이 있어 추천에 반영되지 않았어요."와 예시 "'조용한 곳이 좋아요'처럼 원하는 점을 적으면 반영돼요.", exhausted "이미 보여 줬거나 거절한 {n}곳은 다시 추천하지 않아요."

옮긴 근거(#588 평가, advise-v4, 23건 × 5회 = 115회): 종류 일치 84/90(93%), 남은 종류 실패 5회는 모두 위 절차를 어긴 것이었다. 도구 호출 224번(평균 1.95번) 중 get_run_evidence 115번(모든 실행의 첫 왕복), simulate_filter 108번, get_run_funnel 1번(입력에 이미 있음)이었다. 115회 모두 왕복마다 도구 하나였다. 반경 시뮬레이션은 근거가 필요 없는데도 다음 왕복에, 서로 독립인 시뮬레이션 2~3번(36회)도 한 왕복씩 따로 불렀다. 근거만 읽고 답한 47회는 첫 왕복이 결정에 쓰이지 않았다. 조언 1회에 평균 5.6초(최대 10.6초)를 HTTP 요청 안에서 기다렸고 약 0.37원이 들었다. 평가셋 25건(23건과 인젝션 2건)은 `agent/tests/cases_advice.json`의 회귀 테스트로 남았다.

## 10. 도구

모델은 유형별로 허용된 읽기 전용 도구만 쓴다. 진단 1회당 호출은 5회, 그중 structure_reasons는 1회까지다(상수는 `llm.prompts`). 도구 호출 한 번은 모델 왕복 한 번이 더 생긴다는 뜻이라 횟수에 상한을 둔다. 상한은 llm이 강제한다: 넘는 호출은 실행하지 않고 `LIMIT_EXCEEDED`, 유형에 없는 도구는 `NOT_FOUND`를 도구 결과로 돌려주고, 상한을 다 쓰면 도구 없이 답하게 한다(#532). 그래서 진단 1회의 모델 요청은 많아야 6번이다.

공통 규칙:

- 읽기 전용이고, 비공개 데이터(2절 2번)는 다루지 않는다. 추천 막힘 전용 도구만 그 run의 요청자에게 그 run의 데이터를 다룬다. 각 도구는 필요할 때 짧은 읽기 세션을 열고 닫는다.
- 반환하는 모든 항목에 참조 id를 붙인다. 출력 검증에 쓴다.
- 결과는 상위 `TOOL_RESULT_MAX_ITEMS`개와 총계로 자른다.
- unknown은 unknown 그대로 돌려준다. 같은 입력이면 같은 출력을 낸다.
- 구성원은 관찰 단위 별칭(m1, m2 …)으로만 나온다. 별칭과 user_id 대응은 agent 코드만 안다.
- 오류는 구조화해서 돌려준다: NOT_FOUND, LIMIT_EXCEEDED, UNAVAILABLE(② 실패로 structure_reasons를 못 함, #533).
- 사유 텍스트는 사용자가 쓴 데이터다. 프롬프트에서 지시로 취급하지 않는다고 명시한다.
- call_id(t1, t2 …)는 llm이 매겨 `tool_runner(call_id, name, args)`로 넘긴다. 모델이 ToolClaim에 그 번호를 쓰려면 도구 결과에 번호가 함께 있어야 하기 때문이다(#532). agent는 받은 call_id로 입력, 결과, 소요 시간을 `agent_runs.tool_calls`에 남긴다. 결과 안의 사유 글은 남기지 않고 `reaction_id`와 글자 수로 바꿔 남긴다(2절 13번). 모델에 보내는 결과에는 글이 그대로 들어간다. 저장할 때만 바꾼다.
- 구현은 `agent/tools.py`에 두고, 각 도구는 다른 모듈의 `api.py`를 감싸기만 한다.

| 도구 | 시그니처와 반환 | 출처 |
| --- | --- | --- |
| get_map_overview | `(map_id)` → dday, member_count, 카테고리별 핀 수와 확정 수, last_activity_at | maps.api, pins.api, shortlist.api |
| get_activity | `(map_id, since)` → 행동 종류별 수, distinct_actors, median_gap_minutes | pins.api, shortlist.api |
| get_reaction_matrix | `(map_id, category)` → members[별칭], pins[{pin_id, name, reactions{별칭: like/against/null}}]. null은 미확인 | pins.api (새로 추가) |
| get_reasons | `(map_id, pin_ids 또는 category, types?)` → [{reaction_id, pin_id, type, text, chips[{chip_id, label, fact_key, wants}], member_alias, updated_at}] | pins.api `list_reasoned_reactions` |
| structure_reasons | `(reaction_ids)` → [{reaction_id, lines[{fact_key 또는 null, wants 또는 null, badge}]}]. 글은 ②, 칩은 칩 표 그대로 | llm.api ② 재사용, (reaction_id, updated_at) 캐시 |
| compare_reasons | `(map_id, pin_id 또는 category)` → [{fact_key, want[], avoid[]}] (♥, 🚫 구분이 붙은 reaction_id 목록)와 충돌 종류 | 코드 계산 |
| get_place_facts | `(place_ids, fact_keys?)` → [{place_id, fact_key, value 또는 null, confidence}]. 이 지도 핀의 place_id만 본다(나머지는 not_found). fact_keys를 줬는데 라벨이 없으면 unknown 행. 실시간 핀은 place_id가 없어 대상이 아니다 | places.api |
| get_readiness | `(map_id, category)` → {category, ready, answered_count, required_count} | recommend.api(#530) |
| get_recent_runs | `(run_id)` → 같은 요청자의 같은 카테고리 최근 run [{run_id, status, result_count, created_at}] | recommend.api (#469 기록 조회 재사용), 추천 막힘 전용 |
| get_run_funnel | `(run_id)` → {result_count, funnel[{label, removed_count}], passed_count} | recommend.api, 추천 막힘 전용 |
| get_run_evidence | `(run_id)` → [{line_id, text, badge, fact_key 또는 null, wants 또는 null, is_active, author_id}]. 요청자 본인 줄인지는 agent가 run의 requested_by와 비교한다(#585) | recommend.api, 추천 막힘 전용 |
| simulate_filter | `(run_id, change{radius_factor?, disable_line_ids?})` → {before, after, gained}. before와 after는 {result_count, funnel, passed_count}. passed_count는 필터를 모두 통과한 곳의 수(상위 3곳을 고르기 전), gained는 after − before를 코드가 계산(#587) | recommend.api, 실제 필터 함수 재사용 |
| get_shortlist | `(map_id)` → [{pin_id, category, visit_order}] | shortlist.api |
| get_route | `(map_id)` → [{region_label, ordered_pin_ids, total_distance_m}] 또는 null | shortlist.api |

유형별 허용 도구:

- stall: get_map_overview, get_reasons, structure_reasons, get_readiness
- split: get_reaction_matrix, get_reasons, structure_reasons, compare_reasons, get_place_facts
- 요약: 도구를 모델이 고르지 않는다. 코드가 get_reasons, structure_reasons, compare_reasons를 차례로 부르고 칸을 나눈다(8절).
- 추천 막힘 조언: 모델 도구가 없다(#749). agent가 recommend.api(get_recent_runs, get_run_funnel, get_run_evidence, simulate_filter)를 직접 부른다(9.1). 위 표의 "추천 막힘 전용" 네 줄은 그 함수의 설명으로 읽는다.

simulate_filter는 recommend의 필터 순서(반경 → 영업종료 → 실격조건 → 중복제외)를 다시 구현하지 않는다. recommend.api가 여는 읽기 전용 시뮬레이션 함수를 부른다. run과 후보를 바꾸지 않는다.

## 11. 모델 출력 스키마와 검증

모델은 숫자를 문장에 직접 쓰지 않고, 검증된 claim을 슬롯으로 참조한다. 서버가 검증한 뒤 슬롯을 채워 렌더하고, FE는 렌더된 문장만 받는다.

### 11.1 스키마

```python
# backend/agent/schemas.py (모델 출력. 구조화 출력 스키마로도 쓴다)

class CountClaim(BaseModel):
    id: str                      # c1, c2 ...
    kind: Literal["count"]
    subject: Literal["pin", "category", "map"]
    subject_id: str | None       # pin_id 또는 카테고리 이름, map이면 None
    metric: Literal["like", "against", "unseen", "confirmed", "pins"]   # 반응은 2종 (#360)
    value: int

class QuoteClaim(BaseModel):
    id: str
    kind: Literal["quote"]
    reaction_id: str
    text: str                    # 대조용. 화면에는 DB 원문을 렌더한다

class RefClaim(BaseModel):
    id: str
    kind: Literal["ref"]
    object: Literal["pin", "reaction", "place"]
    ref_id: str

class ToolClaim(BaseModel):
    id: str
    kind: Literal["tool_result"]
    call_id: str                 # llm이 매긴 도구 호출 id(10절, #532)
    path: str                    # 결과 안의 경로. 예: "after"
    value: int | float | str | bool

Claim = CountClaim | QuoteClaim | RefClaim | ToolClaim
# discriminator를 걸지 않는다. 걸면 JSON 스키마가 oneOf가 되는데 엘리스 API가 구조화 출력에서 oneOf를 거절한다(#532).
# kind가 클래스마다 다른 Literal이라 검증 결과는 같다. 정의는 llm/schemas.py 한 곳이고 agent는 그것을 가져다 쓴다

class AdviceLine(BaseModel):
    text: str                    # 슬롯 {c1.value}, {c3}만 허용. 숫자 직접 금지
    basis: list[str]             # claim id
    is_guess: bool               # 추정 문장이면 True

class Action(BaseModel):
    type: Literal["open_recommend", "show_pins", "search_place", "open_route",
                  "widen_radius", "open_evidence"]
    category: str | None = None
    pin_ids: list[str] | None = None
    basis: list[str]

# 2026-10-15: Stance와 모델이 내던 Conflict를 없앴다. 키와 방향은 ②가, 충돌 종류는 코드가 정한다(6.3, 8.1).
# 충돌 분석은 core.compare_reasons의 결과(코드 dataclass)를 모델 입력으로 주고, 저장의 analysis 칸에도 그대로 쓴다.

class DiagnosisOutput(BaseModel):
    decision: Literal["suggest", "silent", "unknown"]
    diagnosis: Literal["stall", "split"]
    signal_id: str
    claims: list[Claim]
    advice: list[AdviceLine]
    actions: list[Action]

# PriorityOutput은 #582에서 지웠다. 우선순위는 코드 규칙이다(7절)

# SummaryOutput은 두지 않는다. 요약의 구체화 문장은 고정 문구다(8절, 2026-10-16). #588에서 모델이 필요하다고 보면 그때 정의한다

# RunAdviceOutput은 #750에서 지웠다. 추천 막힘 조언은 모델 출력이 아니라 코드가 정한다(9.1, 결정 #749)
```

### 11.2 검증 단계

추천 막힘 조언은 모델 출력이 아니라 이 검증을 거치지 않는다(#749). 본인 줄에만 버튼을 붙이는 규칙과 고정 문장은 코드가 지키고 `agent/tests/test_advice_cases.py`(평가셋 25건)가 본다.

`core.verify_*` 함수가 아래 순서로 검사한다. 단계별 통과와 실패 내역은 `agent_runs.verification`에 남긴다.

| 단계 | 검사 | 실패 시 |
| --- | --- | --- |
| 1. 스키마 | pydantic 검증. decision이 silent 또는 unknown인지 | outcome=invalid_schema, silent, unknown으로 침묵. 재요청하지 않음 |
| 2. 진단 성립 | signal_id와 diagnosis가 이번 관찰의 1순위 신호와 같은가 | 침묵 (invalid_claims) |
| 3. claim 대조 | count는 스냅샷에서 같은 지표를 다시 계산해 비교. quote는 공백 정규화 후 해당 reaction 원문에 포함되는지. ref는 이 지도의 공개 데이터에 존재하는지. tool_result는 이번 관찰 도구 로그의 call_id와 path 값이 같은지 | 실패한 claim 제거 |
| 4. 구조 대조 | 요약의 요청 문장이 가리키는 reaction이 vague_fixable 칸에 있는지(not_filtered 사유에 구체화 요청을 붙이지 않았는지) | 해당 문장 제거 |
| 5. 문장 | basis에 제거된 claim이 있는 문장. 슬롯 밖 숫자(정규식 `\d`). 구성원 표시 이름 포함. 금지 표현(FORBIDDEN_PHRASES). 슬롯 밖에서 사유 원문을 옮겨 쓴 문장(입력 사유와 공백을 뺀 연속 8글자 이상 일치, 초안) | 문장 제거 |
| 6. 행동 | 유형별 허용 목록에 있는지. open_recommend의 category가 `categories.recommendable()`인지. open_evidence가 가리키는 근거 줄이 run 요청자 본인 줄인지(9절). basis가 유효한지 | 행동 제거 |
| 7. 성립 판정 | 유형의 필수 claim이 남았는지(split: 해당 핀 like와 against count). 문장이나 행동이 하나 이상 남았는지 | 침묵 (invalid_claims) |

```python
# 초안. 확정이나 결정을 지시하는 표현을 막는다
FORBIDDEN_PHRASES = ("확정하세요", "확정해", "확정하라", "결정하세요", "결정하라", "여기로 가세요", "여기로 정하세요")   # 명령형 둘은 #534
# 슬롯 밖 글(검증 5단계)과 렌더한 text 조각에만 건다(#717). 구성원 글은 quote 조각으로 따로 내려 이 검사를 거치지 않는다.
# #534 때는 인용 슬롯이 반응 글 전체로 바뀌어 사유 글 속 지시문이 화면에 나갔다(평가셋 e05). 걸리면 그 문장을 뺀다
```

렌더(2026-10-24 개정, #717): 응답의 문장은 한 문자열이 아니라 조각 목록(`AgentAdviceLine.segments`)이다. 에이전트의 말과 구성원이 쓴 글을 섞지 않고, 구성원 글은 데이터로 따로 내린다(멘토 리뷰 #680).

- `{cN.value}`(count, tool_result)는 검증된 값으로 채워 앞뒤 슬롯 밖 글과 함께 `text` 조각이 된다.
- `{cN}`(quote)은 `quote` 조각이 된다. 검증할 때 그 인용이 반응 글의 어느 범위인지(시작, 끝)와 그 범위의 다이제스트를 claim에 저장하고, 렌더할 때 지금 원문에서 그 범위만 잘라 다이제스트가 같을 때만 낸다. 다르면(사유가 고쳐졌으면) 그 문장을 뺀다. 원문 전체를 내지 않는다. 전에는 검증은 "인용이 글 안에 있는가"만 보고 화면에는 글 전체를 넣어, 검증한 것과 내보내는 것이 달랐다.
- 인용 길이는 `QUOTE_MAX_CHARS`(초안 60자)까지다. 넘으면 claim을 뺀다.
- `{cN}`(ref pin)은 `pin` 조각이 된다(핀 이름도 실시간 핀이면 사용자가 친 글이다).
- 알러지 사유(8절 not_filtered)를 가리키는 quote는 렌더하지 않고 그 문장을 뺀다. 인용한 반응이나 핀이 지워졌으면 그 문장을 뺀다.
- 금지 표현(FORBIDDEN_PHRASES) 검사는 `text` 조각에만 거는 마지막 확인이다. 목록은 막을 말을 하나씩 늘리는 방식이라 빠지는 표현이 있다("이 핀으로 결정해 주세요", "확정합시다"). 막는 장치는 "구성원 글은 데이터로만 내린다"는 구조이고, 빠지는 표현은 평가셋(`backend/llm/tests/eval_agent/`)의 인젝션 케이스로 잡는다.

저장과 렌더 시점(2절 13번): 테이블에는 슬롯 문장과 검증을 통과한 claim만 저장한다. QuoteClaim의 `text`(대조용)는 검증 뒤 버리고 `reaction_id`, 인용 범위(시작, 끝), 그 범위의 다이제스트만 남긴다(#717). 다이제스트로는 원문을 되살릴 수 없다. 렌더는 `GET /maps/{mapId}/agent` 응답과 `agent.suggested` 이벤트를 만들 때 한다. 이벤트 페이로드에는 렌더된 문장이 들어가지만 event_log는 24시간만 보존되므로(events.md) 허용한다.

M1-2(#533) 구현에서 정한 것:

- 모델 유형 제안의 제목과 버튼 이름은 코드 문구다. DiagnosisOutput에 제목과 label 칸이 없다. 정체는 "{카테고리} 후보가 반대 의견 뒤로 멈춰 있어요", 갈림은 "의견이 갈린 핀이 있어요". 버튼 이름은 코드 유형과 같은 문구(핀만 고른 show_pins는 "핀 보기").
- 5단계: 별칭(m1)도 이름으로 보고 뺀다. 표시 이름은 두 글자 이상만 본다. 이름 검사를 숫자 검사보다 먼저 한다(별칭에 숫자가 있다). 금지 표현과 옮겨 쓰기는 공백을 빼고 비교한다. 300자가 넘는 문장도 뺀다. 표시 이름은 스냅샷 때 읽고 모델에는 보내지 않는다.
- 3, 6단계: 같은 claim id가 두 번 오면 둘 다 버린다. show_pins의 pin_ids는 스냅샷에 있는 핀이어야 한다. 행동 카테고리가 비면 신호의 카테고리를 쓴다. 같은 행동은 하나만 남긴다.
- count claim의 unseen: 핀이면 그 핀을 찍지 않은 구성원 중 반응하지 않은 사람 수, 카테고리와 지도면 그런 사람이 한 명이라도 있는 핀 수.
- analysis는 compare_reasons 결과(충돌 종류, 키, reaction_id)로 저장하고, 화면 모양(AgentAnalysis)은 렌더 때 만든다.
- 모델 결과의 outcome: 호출 실패와 타임아웃은 model_failed, 스키마 실패는 invalid_schema, 검증 실패는 invalid_claims, 그 밖에는 silent, unknown, suggested.

한계: 문장의 의미 자체는 코드로 검증하지 못한다. "♥ 세 명 모두 분위기를 좋아한다"처럼 개수와 의미를 섞은 주장은 걸러지지 않는다. 수치는 슬롯으로만 쓰게 하고, 의미 주장은 is_guess로 표시하게 하고, 나머지는 평가셋으로 잡는다.

## 12. 실행 구조

### 12.1 트리거

관찰 로직은 `flows.run_tick(now)` 하나다. 트리거는 이 함수를 부르기만 한다.

- 개발과 시연: 환경 변수 `AGENT_LOOP_IN_PROCESS=1`(`common/settings.py`, 기본 꺼짐)이면 lifespan에서 `TICK_INTERVAL_SEC`마다 `run_tick`을 부르는 반복 작업을 띄운다. 개발 환경에서만 상주 상태가 하나 늘어난다. 종료 순서(#130)에 이 작업의 정지 대기를 넣는다.
- 배포: Cloud Scheduler가 5분마다 `POST /internal/agent/tick`을 호출한다. 서비스 계정 OIDC 토큰으로 인증한다(초안). 요청 타임아웃 안에 끝나도록 tick당 `TICK_MAX_MAPS`개만 처리하고 나머지는 다음 tick으로 넘긴다.

### 12.2 run_tick

```python
def run_tick(now: datetime) -> list[str]:
    claims, due = service.claim_maps(now, limit=TICK_MAX_MAPS)   # 아래 SQL. lease를 잡는다
    for claim in claims:
        try:
            if 시작 뒤 TICK_BUDGET_SEC가 지나지 않았으면:   # 지났으면 관찰하지 않고 lease만 푼다(커서 그대로, #677)
                observe_map(claim.map_id, now)   # 예외는 안에서 error 행으로 남긴다(아래). 다른 지도는 계속
        finally:
            service.release_lease(claim.map_id)
    daily_cleanup_if_due(now)    # 하루 한 번: agent_runs 30일 초과분 삭제
    처리량 로그 한 줄(#756)
```

관찰이 예외로 끝나면 agent_runs에 outcome=error 한 행을 남긴다(#677). `outcome_detail`은 단계와 예외 클래스 이름(`{stage, error}`)뿐이고 예외 메시지는 남기지 않는다. 단계는 expire, snapshot, detect, draft, model, verify, save, summary다. 진단을 부른 뒤의 실패면 used_model=true와 그때까지의 사용량을 남겨 지도 상한에 센다. 커서는 claim 때 본 seq로 올리고, 다음 관찰은 그 지도의 연속 실패 수에 따라 `ERROR_RETRY_DELAYS` 뒤다.

끝날 때 처리량을 숫자로만 한 줄 남긴다(#756): 차례였던 지도 수(`due`), 관찰한 수, `TICK_MAX_MAPS`로 미룬 수, 시간 예산(`TICK_BUDGET_SEC`, #677)으로 미룬 수, 걸린 ms. 지도 id는 넣지 않는다. 시간 예산으로 미룬 지도가 있으면 warning이다. 읽는 법은 `deploy_rules.md`「배포 뒤 볼 지표」.

event_log를 읽는 곳은 realtime뿐이다(data-model.md common 절). 그래서 claim_maps는 event_log를 조인하지 않고 두 단계로 나눈다(2026-10-15 개정).

1. `realtime.api.latest_seq_by_map(db)`로 지도별 가장 큰 seq와 그 이벤트의 created_at을 받는다(event_log 보존 24시간 안의 지도만). 커서 행이 없는 지도는 이때 upsert한다.
2. 아래 SQL로 lease를 잡는다. `:changed`는 1단계 결과 중 `max_seq > last_seen_seq`인 지도다.

```sql
-- service.claim_maps (개념 SQL)
SELECT c.map_id FROM agent_cursors c
LEFT JOIN agent_settings s ON s.map_id = c.map_id   -- agent 소유 테이블
WHERE coalesce(s.enabled, true)
  AND (c.lease_until IS NULL OR c.lease_until < :now)
  AND ( c.map_id = ANY(:changed) OR c.next_check_at <= :now )
ORDER BY c.next_check_at NULLS LAST
LIMIT :limit
FOR UPDATE OF c SKIP LOCKED;
-- 같은 트랜잭션에서 lease_until = now + LEASE_SEC 로 갱신하고 커밋한다
```

maps 테이블은 agent 소유가 아니므로 조인하지 않는다. 여행 종료와 지도 삭제(`maps.deleted_at`, #369) 판정은 observe_map이 스냅샷에서 한다(12.4의 2단계 직후). 끝난 지도는 커서만 올리고 next_check_at을 null로 둔 채 끝낸다. 그러면 새 이벤트가 올 때만 다시 잡히고, 그때도 바로 끝난다.

agent_cursors 행은 지도 생성 시가 아니라 첫 이벤트를 본 시점에 만든다(초안). 행이 없는 지도는 1단계 결과로 upsert한다.

### 12.3 개입 정책

`core.check_policy(signals, history, snapshot, now)`가 모델 호출 전에 신호를 거른다. 순서는 다음과 같다.

1. 활성 제안이 있고 이번 관찰에서 무효화되지 않으면 새 제안을 내지 않는다(blocked: active_exists). 무효화 판단은 정책보다 먼저 한다(12.4의 3단계).
2. fingerprint가 같은 제안이 이 지도에 accepted, dismissed, expired 상태로 있으면 거른다(blocked: duplicate). superseded는 사람이 내린 판단이 아니므로 다시 낼 수 있다.
3. 백오프 중이면 거른다(blocked: backoff).
4. no_reaction은 오늘 이미 냈으면 거른다(blocked: daily_limit).
5. 모델 사용 상한에 도달했으면 모델 유형을 거른다(blocked: model_cap). 코드 유형은 통과하고, 우선순위는 fallback_order로 정한다.

저장 단계에서 하나 더 거른다: 저장 트랜잭션이 지도 행을 잠근 뒤 모드를 다시 보고, 그사이 꺼졌으면 넣지 않는다(blocked: mode_off, #531). 모드 끄기(`PUT .../agent/settings`)도 같은 지도 행을 잠가 줄을 선다.

```python
def backoff_until(history: list[Suggestion], diagnosis: str, category: str | None) -> datetime | None:
    streak, last_dismissed_at = 0, None
    for sug in history:                              # 같은 지도, 최신순
        if (sug.diagnosis, sug.category) != (diagnosis, category):
            continue
        if sug.status == "accepted":
            break                                    # 수락하면 초기화
        if sug.status == "dismissed":
            streak += 1
            last_dismissed_at = last_dismissed_at or sug.resolved_at
        # expired, superseded는 세지 않는다
    if streak == 0:
        return None
    hours = BACKOFF_HOURS[min(streak, len(BACKOFF_HOURS)) - 1]
    return last_dismissed_at + timedelta(hours=hours)

def model_cap_reached(runs_today: int, member_count: int) -> bool:
    # runs_today: KST 자정 이후 이 지도의 agent_runs 중 used_model=true이고
    #             trigger in (activity, time, summary)인 행 수
    return runs_today >= member_count * PER_MEMBER_DAILY_MODEL_USES
```

### 12.4 observe_map

```python
def observe_map(map_id: str, now: datetime) -> None:
    # 1. 만료 정리 (짧은 쓰기)
    with session_scope() as db:
        service.expire_suggestions(db, map_id, now)       # expired + agent.resolved

    # 2. 스냅샷과 이력 (짧은 읽기, REPEATABLE READ). 여기서 세션을 닫는다
    with read_session(isolation="REPEATABLE READ") as db:
        snap = snapshot.build(db, map_id, now)
        hist = service.load_history(db, map_id, now)

    if snap is None or snap.map.deleted or snap.today > snap.map.end_date:   # 정리됐거나 삭제된 지도(#369), 여행 종료
        with session_scope() as db:
            service.insert_run(db, map_id, ..., outcome="map_deleted" 또는 "trip_ended")   # shadow 측정용으로 기록은 남긴다
            if snap is not None:                          # 정리된 지도(build가 None)는 커서 행도 없다
                service.advance_cursor(db, map_id, snap.latest_seq, next_check_at=None)
        return

    # 3. 탐지와 활성 제안 무효화 판단 (순수)
    th = core.time_threshold(snap.action_times, snap.map.start_date, snap.today)
    signals = core.detect_all(snap, now, th)
    supersede_ids = core.find_superseded(hist.active, signals)   # 신호가 사라졌거나 evidence_hash가 바뀜

    # 4. 정책 사전 검사 (순수)
    passed, blocked = core.check_policy(signals, hist, snap, now, superseding=supersede_ids)

    # 5. 우선순위 (필요하면 모델)
    top, priority_log = choose_top(passed, snap, policy)   # 코드 규칙(7절, #582)

    # 6. 제안 초안
    draft, tool_log = None, []
    if top and top.diagnosis in MODEL_TYPES:
        ctx = tools.Context(map_id=map_id, snapshot=snap, allowed=tools.ALLOWED[top.diagnosis])
        out = llm.agent_diagnose(core.diagnosis_input(top, snap), tool_runner=ctx.run)
        tool_log = ctx.log
        draft = core.verify_diagnosis(out, top, snap, tool_log)     # 실패면 None
    elif top and top.diagnosis in CODE_TYPES:
        draft = core.render_template(top)                # 슬롯 문장과 참조만. 핀 이름은 렌더 때 읽는다(#531)

    # 7. 저장 (짧은 쓰기 트랜잭션)
    with session_scope() as db:
        if not maps_api.lock_map_if_alive(db, map_id):    # 지도 행 잠금 + 삭제 확인 (architecture.md 1.1 동시성, #435)
            return                                        # 모델 호출 중 지도가 삭제됐다. 아무것도 쓰지 않는다
        if draft and not core.recheck(draft, snapshot.build(db, map_id, now), th):   # 같은 트랜잭션에서 스냅샷을 다시 만들어 탐지기를 다시 돈다
            draft = None                                  # outcome = stale
        service.supersede(db, supersede_ids)              # + agent.resolved
        run = service.insert_run(db, map_id, snap, signals, blocked, priority_log, tool_log, outcome)   # 제안이 run_id를 가리키므로 먼저
        if not settings_enabled(db, map_id): ...          # 잠근 뒤 모드 재확인. 꺼졌으면 blocked(mode_off)
        shadow = top.diagnosis in SHADOW_DIAGNOSES
        sug = service.insert_suggestion(db, draft, run, shadow=shadow) if draft else None
        # insert는 ON CONFLICT (map_id) WHERE status='active' DO NOTHING. 안 들어가면 그 run의 outcome을 blocked(active_exists)로 고친다
        if sug and not shadow:
            record_event(db, agent_suggested_event(sug))
        nca = core.next_check_at(snap, hist, now, th)    # 방금 넣은 제안의 expires_at도 후보에 넣는다
        if core.has_recent_event(snap.latest_event_at, now):   # 12.5 보완: 늦은 커밋을 다음 tick에 한 번 더 본다
            nca = now if nca is None else min(nca, now)
        service.advance_cursor(db, map_id, snap.latest_seq, next_check_at=nca)

    # 8. 요약 (별도 흐름, 별도 트랜잭션)
    update_summary(map_id, snap, hist, now)
```

M0(#515) 구현에서 정한 것: 모델 유형이 1순위면 M0에서는 코드 유형으로 내려가지 않고 outcome=silent로 기록한다(M1과 같은 빈도를 shadow로 보려는 것). 제안의 created_at은 DB 시각이 아니라 관찰 시각(now)이라 하루 1회와 백오프가 같은 시계를 본다.

`core.next_check_at`은 시간 기준이 가장 먼저 만료될 시각을 돌려준다. 후보는 전제를 만족한 정체 카테고리의 t0 + th, 갈림 후보 핀의 마지막 반응 + th, 반응 공백 대상 핀이 기준 시간에 도달하는 시각, 활성 제안의 expires_at이다. 후보가 없으면 null이다.

### 12.5 커서와 lease

커서는 "이 지도는 event_log seq 몇 번까지 확인했다"를 적은 책갈피다. 메모리가 아니라 `agent_cursors`에 둔다. 배포나 오류로 프로세스가 다시 떠도 값이 남고, 인스턴스가 여러 개여도 하나다. 커서는 제안 저장과 같은 트랜잭션에서 올려서, 저장은 실패했는데 커서만 넘어가는 일이 없게 한다.

**커서는 "본 것 중 가장 큰 seq"다(2026-10-15 개정).** 10/2 판은 realtime처럼 지도별로 seq가 빈자리 없이 이어지는지 보고 구멍에서 멈췄다. 그런데 event_log seq는 모든 지도가 함께 쓰는 번호라, 지도 하나의 seq에는 다른 지도 몫의 빈 번호가 늘 있다. 그대로 두면 그 빈 번호를 커밋 순서 구멍(events.md 4번)으로 착각해 tick마다 하나씩만 넘어가고, 그동안 지도가 계속 "새 이벤트 있음"으로 잡힌다(#522 realtime 보고).

- 관찰이 끝나면 `last_seen_seq`를 스냅샷 시점의 가장 큰 seq로 올린다. 구멍은 추적하지 않는다.
- 놓칠 수 있는 것: 더 작은 seq를 받은 트랜잭션이 관찰 뒤에 커밋되면 그 이벤트로는 관찰이 시작되지 않는다. 상태는 늘 도메인 테이블에서 읽으므로 데이터를 잃지는 않고, 다음 이벤트나 시간 점검 때 반영된다. realtime도 2초 넘게 늦은 커밋은 건너뛴다.
- 보완: 관찰할 때 그 지도의 가장 최근 이벤트가 `RECENT_EVENT_GRACE`(2초) 안에 생겼으면, 커서는 그대로 올리되 `next_check_at`을 지금으로 당겨 다음 tick에 한 번 더 관찰한다. 그사이 늦게 커밋된 이벤트도 그 관찰에 들어간다. 상태를 더 두지 않는 조건 한 줄이다.

```python
RECENT_EVENT_GRACE = timedelta(seconds=2)   # realtime/core.py GRACE와 같은 값

def has_recent_event(latest_event_at: datetime | None, now: datetime) -> bool:
    return latest_event_at is not None and now - latest_event_at < RECENT_EVENT_GRACE
```

lease는 12.2의 SQL이 잡고, 관찰이 끝나면 `release_lease`가 비운다. 프로세스가 중간에 죽어도 `LEASE_SEC` 뒤에는 다른 실행이 가져갈 수 있다.

### 12.6 DB 세션

모델 호출 중에는 DB 세션을 들고 있지 않는다. 연결 풀은 개수가 정해진 공용 자원이라, 수십 초 걸리는 모델 호출 동안 붙잡고 있으면 다른 사용자의 요청이 연결을 기다린다.

1. 짧게 열어 스냅샷을 읽고 닫는다.
2. 모델을 호출한다. 도구는 필요할 때 자기 세션을 짧게 열고 닫는다.
3. 다시 짧게 열어 재확인과 저장을 하고 커밋한다.

`run_tick`은 요청 단위 세션(get_db) 밖에서 돈다. `/internal/agent/tick` 라우터도 get_db를 쓰지 않는다.

### 12.7 스냅샷

`snapshot.build`는 도메인 테이블에서 필요한 것만 읽어 묶은 읽기 전용 객체를 만든다. 관찰 한 번 동안 탐지기, 모델 입력, 검증이 모두 같은 사본을 본다.

- 하나의 REPEATABLE READ 트랜잭션으로 읽어 테이블 간 시점을 맞춘다.
- 공개 데이터만 담는다: maps(삭제 여부 포함), memberships, 삭제되지 않은 핀, 반응과 사유(삭제된 핀의 사유 포함, 8절), shortlist_items. 모두 다른 모듈의 `api.py`로 읽는다.
- run은 카테고리별 마지막 생성 시각만 담는다(`has_run_since`용). 후보와 근거는 담지 않는다.
- 구성원 별칭(m1, m2 …)을 여기서 매긴다.
- `latest_seq`, `latest_event_at`: 이 지도의 가장 큰 seq와 그 이벤트의 created_at(`realtime.api.latest_seq_by_map`, 12.5).
- event_log는 "바뀐 게 있는가"와 커서 계산에만 쓴다. 상태는 도메인 테이블에서 읽는다.

### 12.8 상태 재확인

`core.recheck`는 저장 트랜잭션 안에서 제안이 근거로 삼은 신호를 같은 탐지기로 다시 계산해, 신호가 그대로 있고 evidence_hash가 같은지 본다. 다르면 제안을 버리고(outcome=stale) 다음 tick에서 새 상태로 판단한다.

seq 비교로 하지 않는 이유는 seq에 커밋 순서 구멍이 생길 수 있어서다. 실제 값을 다시 계산하면 이 구멍과 무관하고, 쿼리 몇 개라 비용도 작다.

### 12.9 정리 작업

- 만료: 관찰 시작 시 `expires_at < now`인 활성 제안을 expired로 바꾸고 agent.resolved를 낸다.
- 무효화: 신호가 사라졌거나 evidence_hash가 바뀐 활성 제안은 superseded로 바꾼다. 신호가 남아 있으면 같은 관찰에서 새 제안이 나올 수 있다.
- 모드를 끄면 활성 제안을 superseded로 바꾼다. 다시 켜면 `next_check_at = now`로 두어 다음 tick에 관찰한다.
- `decided_within_24h`: 하루 한 번 정리 때, 생성 후 24시간이 지난 제안에 대해 확정이 생겼는지 계산해 채운다(#613). category_gap과 stall은 그 카테고리의 핀, split은 그 핀, no_reaction은 제안이 가리킨 핀 중 하나가 제안 시각부터 24시간 안에 확정됐으면 참이다. **판정은 정리 시점까지 남아 있는 확정 항목 기준이다.** 24시간 안에 확정했다가 정리 전에 리스트에서 빼면 거짓으로 남는다. 확정 이력을 따로 두지 않아서이고, 결정을 도왔는지 대략 보는 지표라 이 오차는 받아들였다(2026-10-19). 삭제된 핀은 분류를 읽지 못해(`pins.api.list_reaction_matrix`는 살아 있는 공개 핀만) category_gap과 stall에서 세지 않는다. 확정 핀을 지우면 확정 항목도 지워져(#235) 드물어서 같은 오차로 받아들인다(#613).
- 보존: 하루 한 번 `agent_runs`의 30일 초과분을 지운다.
- 지도 정리: 삭제한 지 30일이 지난 지도를 지우는 작업(`python -m maps.purge`, #431)이 모듈마다 `purge_map_data`를 부른다. agent도 `agent.api.purge_map_data`를 열어 agent_* 7개 테이블의 그 지도 행을 지운다.
- 탈퇴: 반응과 근거 줄은 탈퇴 때 실제로 지운다(#155). agent 테이블에는 사유 원문이 없으므로(2절 13번) 반응이 지워지면 인용도 렌더되지 않는다. `agent.api.delete_by_user(db, *, user_id, map_ids)`(#513)는 그 사람의 열람 기록을 지우고, 안전장치로 map_ids 지도의 요약을 지우고 agent_runs의 tool_calls와 verification을 비운다. 탈퇴 흐름이 `maps.api.lock_member_maps`로 잡은 지도 목록을 넘긴다(#512). 요약은 다음 관찰에서 다시 만든다.
- 지도 나가기(#369): 나간 사람의 반응이 지워지므로 활성 제안의 evidence_hash가 바뀌고, 다음 관찰에서 superseded가 된다. 따로 처리하지 않는다.

## 13. 데이터 모델

agent 모듈이 소유하는 테이블은 7개다. 마이그레이션은 현재 head 다음 리비전으로 추가한다. map_id는 다른 모듈과 같이 String이고 FK는 걸지 않는다(모듈 경계를 넘는 FK는 걸지 않는 관례, #760).

```sql
-- 지도별 모드. 행이 없으면 on으로 간주한다 (기본값 on)
CREATE TABLE agent_settings (
  map_id      text PRIMARY KEY,
  enabled     boolean NOT NULL,
  updated_by  text NOT NULL,
  updated_at  timestamptz NOT NULL DEFAULT now()
);

-- 책갈피, 다음 시간 점검 시각, 중복 실행 방지 자리표. 관찰 흐름만 쓴다
CREATE TABLE agent_cursors (
  map_id            text PRIMARY KEY,
  last_seen_seq     bigint NOT NULL DEFAULT 0,
  -- gap_seq: 10/2 판의 구멍 추적용. 12.5 개정으로 0030에서 지웠다(#515)
  last_observed_at  timestamptz NULL,
  next_check_at     timestamptz NULL,     -- 시간 기준이 가장 먼저 만료될 시각
  lease_until       timestamptz NULL
);

-- 관찰 한 번의 기록. 침묵으로 끝난 관찰도 남긴다. 30일 보존
CREATE TABLE agent_runs (
  id              uuid PRIMARY KEY,
  map_id          text NOT NULL,
  started_at      timestamptz NOT NULL,
  finished_at     timestamptz NULL,
  trigger         text NOT NULL,          -- activity | time | summary | run_advice
  snapshot_at     timestamptz NULL,
  snapshot_seq    bigint NULL,
  signals         jsonb NOT NULL DEFAULT '[]',
  blocked         jsonb NOT NULL DEFAULT '[]',   -- [{signal_id, reason}]
  priority        jsonb NULL,             -- source(single|rules), final_order, fingerprints, rule_hits (#582)
  policy_version  text NULL,
  prompt_version  text NULL,             -- 우선순위와 진단을 둘 다 부르면 "prioritize-v1+diagnose-v1"처럼 잇는다. model도 같다(#564)
  model           text NULL,
  used_model      boolean NOT NULL DEFAULT false,
  tool_calls      jsonb NOT NULL DEFAULT '[]',
  verification    jsonb NULL,
  tokens_in       integer NOT NULL DEFAULT 0,   -- 한 관찰의 모델 왕복 전부의 합. 실패한 호출도 그때까지 쓴 양을 센다(#564)
  tokens_out      integer NOT NULL DEFAULT 0,
  outcome         text NOT NULL,          -- 아래 목록
  outcome_detail  jsonb NULL
);
CREATE INDEX ix_agent_runs_map_started ON agent_runs (map_id, started_at);
-- outcome: no_signal | blocked | silent | unknown | invalid_schema | invalid_claims | model_failed
--          | stale | suggested | summarized | advised | trip_ended | map_deleted | error
-- error: 관찰이나 조언이 예외로 끝남. outcome_detail은 단계와 예외 클래스 이름뿐(#677, 12.2)
-- model_failed: 모델 호출 실패나 타임아웃(AgentCallFailed, #532). 이유는 outcome_detail. 재요청하지 않고 침묵한다

-- 바텀시트에 뜨는 지도 제안
CREATE TABLE agent_suggestions (
  id                  uuid PRIMARY KEY,
  map_id              text NOT NULL,
  run_id              uuid NULL REFERENCES agent_runs(id) ON DELETE SET NULL,
  diagnosis           text NOT NULL,      -- stall | split | no_reaction | category_gap
  category            text NULL,
  pin_id              uuid NULL,
  fingerprint         text NOT NULL,
  evidence_hash       text NOT NULL,
  title               text NOT NULL,      -- 슬롯 문장. 렌더는 응답과 이벤트를 만들 때(#531)
  claims              jsonb NOT NULL,     -- 검증 통과분. quote는 reaction_id만(원문 없음, 2절 13번)
  analysis            jsonb NULL,         -- split의 충돌 지점 등
  advice              jsonb NOT NULL,     -- [{slot_text, is_guess}] 슬롯 문장만. 렌더 결과는 저장하지 않는다
  actions             jsonb NOT NULL,     -- [{index, type, label, params}]
  status              text NOT NULL,      -- active | accepted | dismissed | expired | superseded
  shadow              boolean NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  expires_at          timestamptz NOT NULL,
  resolved_by         text NULL,          -- 기록만 한다. 화면과 이벤트에 싣지 않는다
  resolved_at         timestamptz NULL,
  resolved_action     jsonb NULL,
  decided_within_24h  boolean NULL
);
CREATE UNIQUE INDEX uq_agent_suggestions_active ON agent_suggestions (map_id) WHERE status = 'active';
CREATE INDEX ix_agent_suggestions_map_fp ON agent_suggestions (map_id, fingerprint);

-- 사용자별 열람. 버튼의 점과 미열람 지표에 쓴다. 첫 열람 시각 = min(viewed_at)
CREATE TABLE agent_suggestion_views (
  suggestion_id  uuid NOT NULL REFERENCES agent_suggestions(id) ON DELETE CASCADE,
  user_id        text NOT NULL,
  viewed_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (suggestion_id, user_id)
);

-- 우리 조건 요약. 카테고리마다 최신본 하나만 덮어쓴다
CREATE TABLE agent_reason_summaries (
  map_id                   text NOT NULL,
  category                 text NOT NULL,
  summary                  jsonb NOT NULL,   -- 다섯 칸의 키, 개수, 근거 reaction_id, 문구 종류(requests, notices). 사유 원문 없음
  based_on_reaction_count  integer NOT NULL,
  run_id                   uuid NULL,
  updated_at               timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (map_id, category)
);

-- 추천 막힘 조언. run당 1행. silent여도 빈 advice로 저장한다
CREATE TABLE agent_run_advice (
  run_id        uuid PRIMARY KEY,           -- recommend_runs.id. 모듈 경계라 FK 없음
  map_id        text NOT NULL,
  kind          text NULL,
  claims        jsonb NOT NULL,             -- quote는 reaction_id만
  advice        jsonb NOT NULL,             -- 슬롯 문장만
  actions       jsonb NOT NULL,
  agent_run_id  uuid NULL,
  created_at    timestamptz NOT NULL DEFAULT now()
);
```

개인 단위 음소거 테이블은 두지 않는다. 모드와 닫기가 지도 단위이고, 백오프는 agent_suggestions 이력에서 계산한다.

## 14. API

정본은 `docs/api-spec.yaml`의 agent 태그와 `GET /runs/{runId}/advice`다(#510, 2026-10-15 반영). 스키마 이름은 AgentState, AgentSuggestion, AgentAction, AgentSummary, RunAdvice 등이다. 이 표는 요약이다. 권한은 `docs/permissions.md` 체계를 따른다: 비구성원 404, 구성원이지만 불가 403.

| 메서드와 경로 | 용도 | 권한과 응답 |
| --- | --- | --- |
| `GET /maps/{mapId}/agent` | 바텀시트 상태(AgentState): settings, active_suggestion(shadow 제외, 모드가 꺼져 있으면 null), has_unseen, summaries[] | 구성원. 200 |
| `PUT /maps/{mapId}/agent/settings` | 모드 변경 `{enabled}`. 끄면 활성 제안 superseded | 구성원 (agent.toggle). 200 AgentSettings, agent.settings_changed |
| `POST /agent/suggestions/{id}/view` | 열람 기록. agent_suggestion_views upsert | 구성원. 204, 이벤트 없음 |
| `POST /agent/suggestions/{id}/accept` | `{action_index}`. status='active'일 때만 바꾸는 가드 UPDATE | 구성원 (agent.suggestion.resolve). 200 `{action}`, 이미 처리됐으면 409 SUGGESTION_RESOLVED |
| `POST /agent/suggestions/{id}/dismiss` | 닫기. 지도 단위로 모두에게서 닫힘 | 구성원 (agent.suggestion.resolve). 204, 이미 처리됐으면 409 |
| `GET /runs/{runId}/advice` | 추천 막힘 조언 (api-spec recommend 태그, 코드는 agent/router.py, 9절) | run 요청자만. 200, 대상 아니거나 조언 없음 204 |
| `POST /internal/agent/tick` | 배포용 tick | 내부 인증만. 202. FE 계약이 아니라 api-spec에 넣지 않는다. 라우트 커버리지 테스트의 `NOT_IN_SPEC`에 더한다 |

- has_unseen: 활성 제안이 있고, 요청자의 agent_suggestion_views 행이 없으면 true.
- accept의 응답 action은 FE가 실행할 기존 동작 설명이다(16.3). 서버는 그 동작을 대신 실행하지 않는다.
- SUGGESTION_RESOLVED(409)는 `docs/errors.md`와 `common/errors.py`에 반영했다(#510).
- 서버 내부 값(claims, 슬롯 원문, fingerprint, resolved_by)은 응답과 이벤트에 싣지 않는다. FE는 렌더된 문장만 받는다.

## 15. 이벤트

전체 채널에 4종을 추가한다. 개인 채널 타입은 없다. `docs/events.md`, api-spec.yaml의 Evt* 스키마, PublicEvent oneOf에 반영했다(#510, EvtAgentSuggested 등). 모든 이벤트는 상태 변경과 같은 트랜잭션에서 `common.events.record_event`로 기록한다. shadow 제안(`SHADOW_DIAGNOSES` 유형)은 내지 않는다. 코드 유형은 #531부터 발행한다.

| type | 언제 | 페이로드 |
| --- | --- | --- |
| agent.suggested | 제안 저장 | AgentSuggestion: id, diagnosis, category, title, analysis, advice[{segments, is_guess}], actions[{index, type, label, params}], created_at, expires_at |
| agent.resolved | 수락, 닫기, 만료, 무효화 | suggestion_id, status, resolved_action_type 또는 null |
| agent.summary_updated | 우리 조건 요약 갱신 | AgentSummary: category, 다섯 칸, updated_at |
| agent.settings_changed | 모드 변경 | enabled, updated_by |

FE가 이벤트를 받고 무엇을 다시 불러오는지는 `docs/events.md`의 다시 불러오기 표(#450)에 4종을 함께 올린다.

agent.resolved에는 resolved_by를 싣지 않는다. 수락한 사람을 화면에 표시하지 않기로 했다(run이 비공개라 5-5-1과 부딪힐 수 있음). agent.settings_changed의 updated_by는 누가 모드를 바꿨는지 구성원 모두에게 알리기 위해 싣는다.

## 16. 화면 (FE)

### 16.1 버튼

- 위치: 지도 탭 좌측 하단, 기존 바텀시트 위. 문구 "핑고 AI 조언".
- 점: `has_unseen`이 true면 버튼에 작은 점을 붙인다. 요약 갱신에는 점을 붙이지 않는다.
- 모드가 꺼져 있어도 버튼은 보인다. 점은 숨긴다.
- 진입 시 `GET /maps/{mapId}/agent`로 상태를 받는다.

### 16.2 바텀시트

1. 상단: 모드 스위치. 꺼져 있으면 "꺼져 있어요"와 스위치만 보인다.
2. 지금 제안 (0개 또는 1개)
    - 제목 (서버 렌더)
    - 확인된 것: is_guess=false 문장
    - 유형별 분석: split이면 충돌 지점. 축마다 "♥ 쪽 / 🚫 쪽"과 same_axis, different_axes 표시
    - AI 조언: is_guess=true 문장. "추정" 표시를 붙인다
    - 행동 버튼(actions의 label)과 닫기
    - 제안이 없으면 "지금은 따로 드릴 제안이 없어요"
3. 우리 조건 요약: 카테고리 탭. 탭마다 4칸(8절)과 "이 조건으로 추천 받기" 버튼.

시트를 열었을 때 활성 제안이 있고 has_unseen이 true면 `POST /agent/suggestions/{id}/view`를 부르고 점을 없앤다.

FE는 슬롯을 다루지 않는다. 서버가 렌더한 조각을 차례로 이어 보여 준다(#717). `text`는 에이전트 문장, `quote`는 구성원 의견으로 보이게 인용 모양(예: 따옴표 안, 다른 글자색이나 배경)으로, `pin`은 핀 이름 모양으로 그린다. 인용에는 누가 썼는지 붙이지 않는다(2절 11번).

### 16.3 행동 실행

버튼은 기존 동작의 지름길이다. 순서는 accept → 기존 동작이다.

1. `POST /agent/suggestions/{id}/accept {action_index}`. 409면 상태를 다시 받아 시트를 갱신한다.
2. 응답의 action을 실행한다.

| action.type | FE가 하는 일 | 쓰는 곳 |
| --- | --- | --- |
| open_recommend | AI 추천 탭으로 이동해 카테고리를 채우고, 손으로 누를 때와 같은 `POST /maps/{id}/runs` 호출 | 지도 제안, 우리 조건 요약 |
| show_pins | 지도 탭 필터 적용 (pin_ids, 카테고리, 미확인) | 지도 제안 |
| search_place | 장소 검색 바텀시트를 카테고리와 함께 연다 | 지도 제안 |
| open_route | 리스트 탭 동선을 연다 | 지도 제안 |
| widen_radius | 기존 반경 넓히기 | 추천 막힘 조언 |
| open_evidence | 근거 확인 화면으로 돌아간다 | 추천 막힘 조언 |

기존 동작이 실패하면(예: ⓪ NotReady 409, 재시도 상한 429) "상황이 바뀌었어요"를 보여준다. 근거 확인, ⓪, 재시도 상한은 손으로 할 때와 똑같이 적용된다.

우리 조건 요약의 버튼은 제안이 아니라 accept를 거치지 않고 바로 open_recommend를 실행한다.

### 16.4 이벤트 처리

- agent.suggested: active_suggestion을 바꾼다. 시트가 열려 있으면 바로 view를 부르고, 닫혀 있으면 점을 켠다.
- agent.resolved: id가 같으면 active_suggestion을 비우고 점을 끈다.
- agent.summary_updated: 해당 카테고리 요약을 바꾼다.
- agent.settings_changed: enabled를 바꾼다. 변경자 표시 이름은 구성원 목록에서 찾는다.
- map.deleted, member.left(본인): 지도에서 나가는 기존 처리를 따른다. agent 상태도 함께 버린다.
- 이벤트 페이로드는 멱등하게 적용한다(events.md 3번).

### 16.5 AI 추천 결과 화면

완료된 run이면 funnel을 먼저 보여준 뒤 `GET /runs/{runId}/advice`를 부른다. 로딩 중에는 조언 영역에 자리만 둔다. 대상인지는 서버가 정한다(9절). 204면 아무것도 보여주지 않는다. 200이면 문장과 버튼(widen_radius, open_evidence)을 보여준다.

## 17. 테스트와 완료 정의

`core.py`가 순수 함수라 대부분은 지도 상태 픽스처를 넣고 기대 신호와 정책 결과를 확인하는 단위 테스트로 짠다. llm은 스키마에 맞는 스텁으로 대신한다.

1. **비공개 데이터 유출 금지 (가장 중요한 테스트).** DB에 남의 run, 후보, run의 근거 줄, 제외 목록을 넣고 다음을 확인한다: 스냅샷에 없음, 모든 지도 제안용 도구 결과에 없음, `diagnosis_input` 직렬화 결과에 그 id와 텍스트가 없음.
2. 조건 완화와 키 없는 사유: soft_relax에서 run 요청자 본인 줄에만 open_evidence가 붙고, 남의 줄에는 코드가 open_evidence를 붙이지 않는다(9.1). 알러지 낱말이 든 사유와 「비싸요」 칩은 not_filtered 칸으로 가고, 구체화 요청 문장을 붙이지 않으며, 원문이 렌더되지 않는다. 「너무 멀어요」는 vague_fixable로 간다.
3. 검증: 지어낸 count → claim 제거 → 필수 claim 없음 → invalid_claims. 원문에 없는 quote 제거. 슬롯 밖 숫자 문장 제거. 구성원 표시 이름이 든 문장 제거. 허용되지 않은 행동 제거. FORBIDDEN_PHRASES 문장 제거.
4. 탐지기 경계: 유형마다 성립 직전과 직후 픽스처. 정체는 활동 기준만, 시간 기준만, 둘 다인 경우. 갈림은 ♥1:🚫3 불성립, 전원 응답 즉시. 충돌 종류는 같은 키 반대 방향이면 same_axis, 다른 키면 different_axes, 키 있는 사유가 한쪽에 없으면 unclear. 반응 공백은 자기 핀 제외, 합류 시각 기준. 카테고리 공백은 핀을 만들 수 없는 카테고리(숙소, 기타) 제외.
5. 기준 시간: 이벤트 6개 미만이면 3시간 × D-day 계수, clamp 하한 1시간과 상한 12시간, D-day 경계(15, 14, 4, 3, 여행 중).
6. 정책: fingerprint 중복, 백오프 2, 6, 24시간과 수락 초기화와 만료 미포함, no_reaction 하루 1회, 모델 상한(구성원 수 × 4, KST 자정), 상한 도달 시 코드 유형 통과와 fallback_order.
7. 상태 재확인: 모델 호출 중 그 핀이 확정되거나 반응이 바뀌면 stale로 저장하지 않는다.
8. 활성 제안 1개: 동시에 두 관찰이 저장해도 active는 하나다(부분 유니크 인덱스).
9. 커서: 관찰 뒤 last_seen_seq가 스냅샷 시점의 가장 큰 seq가 된다. 다른 지도 몫의 빈 번호가 있어도 다음 tick에 다시 잡히지 않는다. 가장 최근 이벤트가 2초 안이면 next_check_at이 지금으로 당겨진다. 저장 트랜잭션이 롤백되면 커서도 그대로.
10. lease: 동시에 두 run_tick이 돌아도 같은 지도는 한 번만 관찰한다.
11. 세션: llm 스텁이 호출되는 동안 열린 DB 세션이 없다.
12. 권한: 비구성원 404. advice는 요청자가 아니면 403. accept와 dismiss 경합 시 두 번째는 409.
13. 추천 막힘 조언: 같은 run에 동시 요청이 와도 저장은 한 번이고 두 요청 모두 같은 결과를 돌려준다. 계산은 두 번 돌 수 있다(막으려면 "만드는 중" 상태 칸이 필요해 하지 않았다, #587). 모델 호출은 없다(#750).
14. 여행 종료와 지도 삭제: end_date 다음 날부터 관찰하지 않고 outcome=trip_ended로 끝난다. 삭제된 지도는 outcome=map_deleted로 끝나고, 모델 호출 중 삭제되면 저장 단계에서 아무것도 쓰지 않는다.
15. shadow: `SHADOW_DIAGNOSES`에 든 유형의 제안은 저장되지만 이벤트가 없고 GET 응답에 나오지 않으며 view, accept, dismiss는 404다.
16. 정리와 원문: `purge_map_data`가 그 지도의 agent_* 행을 모두 지운다. 픽스처 반응의 글이 관찰과 요약과 조언을 거친 뒤 어떤 agent_* 행의 직렬화에도 들어 있지 않다(2절 13번). 반응을 지우면 그 인용 문장이 응답에서 빠진다. 모델 문장이 슬롯 밖에서 사유를 옮겨 쓰면 문장이 제거된다.
17. 요약 칸 나누기: #422 규칙으로 선호가 된 음식 종류 "원함"이 must_keep에 들어가지 않는다. 같은 사람이 같은 키를 두 번 말해도 1명으로 센다.

## 18. 마일스톤과 작업 목록

M1과 M2는 하나로 묶었다. 단계는 M0, M1, M2, 이후 순서다. 각 단계 앞의 통과 조건을 먼저 끝낸다.

### M0: shadow 기반 (모델 호출 없음)

통과 조건: 없음

AI 담당

- [x] 모델 호출 추가 결정 이슈를 연다(#509). 팀 결정은 M1 통과 조건이다
- [x] #509 결정 뒤 루트 문서 개정: `/CLAUDE.md` 모델 호출 절, `backend/llm/CLAUDE.md`, 기획안 8절과 15절 미결 항목, "모델 호출 2곳" 문구. `llm/api.py` 머리말은 M1에서 agent 함수를 열 때 고친다
- [x] `docs/data-model.md`, `docs/permissions.md`(agent.toggle, agent.suggestion.resolve), `docs/events.md`(이벤트 4종과 다시 불러오기 표), `docs/api-spec.yaml`, `docs/errors.md`(SUGGESTION_RESOLVED) 반영 (#510)
- [x] #513 `backend/agent` 골격, deps.py(Gateway), models.py와 마이그레이션 (13절 7개 테이블, 지금 head 다음 번호)
- [x] #511 pins.api에 반응 표 조회 함수 추가 (pins 모듈 규칙을 따른다). 사유 조회는 기존 `list_reasoned_reactions`를 쓴다
- [x] #512 maps.api에 지도 행 잠금과 삭제 확인 함수(`lock_map_if_alive`) 추가, 지도 정리와 탈퇴에 agent 연결 (maps, auth 담당 리뷰)
- [x] #522 스냅샷과 커서용 읽기 함수: maps(지도와 구성원), shortlist(확정 항목), recommend(카테고리별 마지막 run 시각), pins(사유 조회에 reaction_id와 updated_at), realtime(`latest_seq_by_map`, 12.5)
- [x] #514 snapshot.py, core.py의 탐지기 4종, 기준 시간, fingerprint와 evidence_hash, check_policy
- [x] #515 run_tick, observe_map(모델 단계는 건너뜀), 개발용 반복 작업(`AGENT_LOOP_IN_PROCESS`)
- [x] 커서, lease, agent_runs 기록, 정리 작업, `purge_map_data`, `delete_by_user`와 각 정리 흐름에 연결
- [x] 17절 테스트 1, 4, 5, 6, 8, 9, 10, 16

FE 담당

- [ ] #516 contracts 목 서버로 버튼, 점, 바텀시트 골격 시작

완료: shadow 로그에서 유형별 발동 빈도를 보고, 표본을 사람이 "개입할 만했나"로 라벨링하기 시작한다.

### M1: 지도 제안 (코드 유형 + 모델 진단 + 우선순위 + 화면)

통과 조건: 모델 호출 추가 결정(#509, 완료), 새 이벤트 타입 4종과 API가 정본 문서에 반영됨(#510, 완료), priority_policy.yaml을 PM이 승인(2026-10-15, 완료)

이슈는 디렉토리와 선행 관계로 나눴다(2026-10-15). 코드 유형(no_reaction, category_gap)을 먼저 화면까지 내고, 모델 유형은 평가 뒤에 노출한다.

AI 담당

- [x] #531 M1-1: 템플릿 렌더(render_template), 14절 엔드포인트 5개(router.py, main.py), 이벤트 4종 기록, Gateway `select()` 등록, 코드 유형 노출. 17절 12, 15
- [x] #530 recommend.api.get_readiness
- [x] #532 llm에 agent_prioritize(#582에서 지움), agent_diagnose(도구 콜백 포함) 추가하고 `llm/api.py`에서 연다. 먼저 고정 응답 스텁으로 통합
- [x] #533 M1-2: tools.py 8개, verify_diagnosis, claim 렌더, apply_priority_rules, observe_map 모델 단계. 17절 2(진단 부분), 3, 7, 11
- [x] #534 M1-3: 프롬프트(우선순위, 진단, 도구 설명문), 평가셋 20건, reasoning_effort 확인과 비교, run당 토큰, shadow 검증 실패율을 본 뒤 모델 유형 노출 결정
- [x] #582 M1 마무리: 모델 유형 노출, 우선순위를 코드 규칙으로, TICK_MAX_MAPS 6
- [ ] #535 M1-4: `/internal/agent/tick`과 배포 예약 실행(배포 환경 결정 #168 대기). 그 전에는 `AGENT_LOOP_IN_PROCESS=1`

FE 담당

- [ ] #516 버튼과 점(has_unseen), 바텀시트(16.2), 모드 스위치
- [ ] #536 view, accept, dismiss 호출과 409 처리, 행동 실행(16.3)과 "상황이 바뀌었어요" 처리, 이벤트 4종 처리(16.4)

완료: 노출 후 유형별 열람률, 수락률, 닫기율을 볼 수 있다.

### M2: 우리 조건 요약 + 추천 막힘 조언 + 수치 조정

통과 조건: recommend.api에 run 조회 함수(get_recent_runs, get_run_funnel, get_run_evidence용), 근거 줄 단위 읽기 전용 시뮬레이션 함수 공개(#585). #422 분류 함수와 키 표시 이름은 #564에서 공개됨

이슈는 2026-10-16에 나눴다. 요약은 #585 없이 시작할 수 있다.

AI 담당

- [x] #585 recommend.api: get_recent_runs, get_run_funnel(추천 가능 장소 단계 포함, #558), get_run_evidence, simulate_filter(필터 순서를 다시 구현하지 않는다)
- [x] #586 M2-1 우리 조건 요약: flows.update_summary, 칸 나누기(8절, 코드), `NOT_FILTERED_CHIP_IDS`, `SAFETY_WORDS`, 구체화 문장은 고정 문구로 시작, agent.summary_updated. 17절 2(키 없는 사유), 17
- [x] #587 M2-2 추천 막힘 조언: llm agent_advise_run, 도구 4종, agent.api.advise_run, `GET /runs/{runId}/advice`(recommend 라우터). 17절 2(조건 완화), 13
- [ ] #588 M2-3 평가와 수치 조정: 조언 프롬프트와 평가셋, 요약 문장에 모델이 필요한지 판단, 운영 기록으로 5절 수치 점검(20절). 조언은 #749에서 코드로 옮겨 프롬프트 평가는 없어졌다

FE 담당

- [ ] #589 바텀시트의 우리 조건 요약 탭, AI 추천 결과 화면의 조언 영역(16.5)

완료: decided_within_24h와 조언 후 재시도 결과 수를 볼 수 있다.

### 이후: 동선 기반 진단

통과 조건: 장소 좌표 오류 수정. 확정 리스트 동선을 진단 입력에 추가한다. 범위는 그때 정한다.

## 19. 측정 후 정할 것

- 서비스 전체 일일 상한: 크레딧 잔량과 run당 토큰 측정값으로 정한다. 정하기 전까지는 지도 상한만 적용한다.
- reasoning_effort: 진단 호출은 none으로 고정이다. 엘리스 API의 chat.completions는 도구 호출을 reasoning_effort=none일 때만 받는다(기본값과 low는 400, #532 확인). low가 필요하면 /v1/responses로 옮겨야 한다(확인 안 함). 우선순위 호출은 #534 비교(none 100%, low 88%, 기본값 90%) 뒤 코드 규칙으로 옮겨 없어졌다(#582). temperature=0은 받지 않는다.
- 요약의 모델 호출: 고정 문구로 정했다(2026-10-16). 맞춤 문장이 필요한지는 #588에서 운영 기록을 보고 판단한다.
- 처리량: `TICK_MAX_MAPS`와 동시 처리 수. 진단 소요 시간과 요청 타임아웃, 배포 뒤 tick 로그(#756)를 보고 정한다. 시간 예산은 150초로 둔다(#754).
- 병렬 도구 호출: 지금은 끈다(`parallel_tool_calls=False`, #532에서 동작 확인). #534에서는 재지 않았다. 진단 1회가 평균 도구 1.5회, 요청 2.5번이라 켜도 왕복 하나를 아끼는 정도다.
- 처리량 참고: live 시험에서 우선순위와 진단(요청 4번)을 합쳐 약 18초였다(#532). 요청 타임아웃은 15초다.

멘토 리뷰에 가져갈 것: 커서와 lease, 저장 트랜잭션 경계, 개발용 반복 작업의 상주 상태.

## 20. 조정 기준

| 상수 | 조정할 때 볼 지표 | 데이터 |
| --- | --- | --- |
| PER_MEMBER_DAILY_MODEL_USES | 상한 도달 빈도 | agent_runs.blocked |
| STALL_ACTIVE_MEMBERS, TIME_MULTIPLIER, TIME_MIN, TIME_MAX | 사람 라벨 대비 탐지 정밀도 | agent_runs.signals + 라벨 |
| RHYTHM_WINDOW_EVENTS, RHYTHM_MIN_EVENTS, RHYTHM_DEFAULT_BASE | 신규 지도의 오탐 수, 지도별 리듬 분포 | agent_runs.signals |
| DDAY_* | 출발 임박 지도의 수락률 | agent_suggestions |
| NO_REACTION_* | 닫기 비율 | agent_suggestions |
| CATEGORY_GAP_MIN_CONFIRMED | 닫기 비율 | agent_suggestions |
| BLOCKED_RUN_* | 조언 후 재시도 결과 수 | agent_run_advice + recommend_runs |
| SUMMARY_NEW_REASONS | 갱신 전후 요약 변화량 | agent_reason_summaries |
| 진단 도구 상한(llm.prompts) | 호출 분포, 상한 도달 run의 검증 실패율 | agent_runs.tool_calls, verification |
| BACKOFF_HOURS | 백오프 후 같은 유형의 수락률 | agent_suggestions |
| SUGGESTION_TTL | 만료 비율, 미열람 비율 | agent_suggestions, agent_suggestion_views |
| TICK_INTERVAL_SEC, LEASE_SEC | 관찰 소요 시간 | agent_runs.started_at, finished_at |

## 21. 품질 점검 기록

무엇을 재는지, 어떤 평가셋으로 쟀는지, 결과와 실패 분석, 그래서 고친 것을 한곳에 모은다(#676). 진단 수치는 #534, #582 평가 기록(옛 `backend/llm/for_Root.md`, #757에서 없앴다)에서 옮겼다. 실행마다 나오는 결과 파일(`backend/llm/tests/eval_agent/results/`)은 커밋하지 않고, 여기에는 판단에 쓴 숫자만 둔다.

### 21.1 진단 (정체, 갈림)

평가셋은 `backend/llm/tests/eval_agent/cases.json`의 지어낸 지도 상태 20건이다. 진단 대상은 정체 8건, 갈림 10건이고, 그중 4건은 침묵이 정답이다(알러지 사유뿐인 정체와 갈림, 지시문뿐인 정체와 갈림). 사유 글은 모두 지어낸 예시다. 두 가지로 돌린다.

- 모델 없이(`test_eval_cases.py`, CI에서 매번): 평가셋의 지도 상태가 지금의 탐지, 정책, 충돌 종류, 진단 입력 규칙과 맞는지 본다. 규칙이 바뀌어 기대값이 낡으면 여기서 먼저 깨진다.
- 실제 모델로(`python -m llm.tests.eval_agent.run_eval`): 케이스마다 5번 부르고, 운영과 같은 검증(`agent.core.verify_diagnosis`)을 거친 결과를 센다.

결과는 2026-10-16, gpt-6-luna, reasoning_effort=none, 18건 × 5회 = 90회다.

| 지표 | 뜻 | 처음 초안 | 고친 뒤(diagnose-v2) |
| --- | --- | --- | --- |
| 호출 실패 | 스키마 실패, 시간 초과, 호출 실패 | 2/90 | 0/90 |
| 결정 일치 | 기대(제안 또는 침묵)와 모델의 decision이 같다 | 87/90 (97%) | 89/90 (99%) |
| 검증 통과 | 제안을 고른 호출 중 11.2 검증 뒤 초안이 남았다 | 63/67 (94%) | 69/69 (100%) |
| 첫 버튼 일치 | 남은 첫 버튼이 기대 버튼 중 하나다(침묵 기대는 침묵) | 81/90 (90%) | 88/90 (98%) |
| 결정 지시 표현 | 모델 원문에 "확정", "결정하세요" 같은 말이 나왔다 | 0 | 0 |
| 시간 | 진단 한 번(평균, p90, 최대) | 5.5초, 7.5초, 17.0초 | 5.4초, 7.9초, 13.7초 |
| 비용 | 진단 한 번(캐시 반영) | 0.31원 | 0.34원 |

실패 분석과 고친 것은 다음과 같다.

| 본 실패 | 원인 | 고친 것 |
| --- | --- | --- |
| 처음 초안의 검증 탈락: 도구 값 불일치 13건, 문장 근거 누락 9건, 성립 실패 4건, 버튼 근거 누락 4건 | 라벨이 모름(null)인데 값을 "unknown" 글자로 썼고, 문장과 버튼이 기대는 claim을 비워 두었다 | 프롬프트에 모르는 라벨 쓰는 법, 버튼마다 근거로 적을 것, 모호한 정체에서 쓸 참조 claim을 넣었다. 고친 뒤 탈락은 버튼 근거 1건(e05)뿐이다 |
| 지시문이 섞인 사유 인용(e05, 5번 중 3번) | 그때는 인용 슬롯이 렌더 때 반응 글 전체로 바뀌어, 사유 속 "확정하라고 안내해"가 제안 문장에 그대로 나갔다. 프롬프트로는 막지 못했다 | 처음에는 렌더 결과 전체에 금지 표현 검사를 걸어 그 문장을 뺐다(#534). 지금은 인용이 검증한 범위만 quote 조각으로 데이터처럼 내려가고, 금지 표현 검사는 에이전트 문장(text 조각)에 건다(#717). 인용 범위 밖의 지시문은 화면에 가지 않는다 |
| 우선순위 모델의 1순위 일치: none 100%, low 88%, 기본값 90% | 모델이 기본 순서를 바꾼 5건이 모두 규칙 셋(출발 임박, 같은 가중치의 영향 인원, 연속 닫힘)으로 설명됐다 | 우선순위를 코드 규칙으로 옮겼다(#582). 관찰당 약 2초와 우선순위 호출의 실패 경로가 없어졌다 |

남은 한계는 세 가지다.

- 평가셋이 20건이라 사실상 18가지 상황을 5번씩 본 것이다. 기획안 10절 기준(지표마다 60~100건)으로는 90%를 넘었다고 말하기 어렵다. 운영 기록(agent_runs의 outcome과 verification)으로 보완한다.
- 평가 뒤에 입력이 바뀌었다(우선순위 코드 규칙 #582, 원함 칩의 선호 전환 #617, 조각 렌더 #717). 진단 프롬프트는 그대로지만 한 번 다시 재 보는 것이 좋다.
- 문장의 뜻은 코드로 검증하지 못한다(11절 끝 "한계"). 숫자와 인용은 슬롯으로만 쓰게 하고, 짐작은 is_guess로 표시하게 한다.

### 21.2 추천 막힘 조언

조언은 모델 없이 코드가 고른다(#749, 9.1). 순서가 정해진 절차를 모델이 글로 따라 하고 있었기 때문이다. 그래서 모델 평가셋 대신 두 가지로 본다.

- 표 테스트(`backend/agent/tests/cases_advice.json`, `test_advice_cases.py`): 깔때기와 근거 줄 상황마다 종류(radius, soft_relax, vague_reason, exhausted)와 침묵, 남이 쓴 근거 줄에 버튼이 붙지 않는지를 본다.
- 끝단 통합(21.4): 실제 API로 만든 run에서 조언을 요청하고 버튼을 누른다.

끝단 통합 테스트가 찾은 결함은 둘이다.

- #677: 조언은 상한(도보 30분)까지 넓힌 시뮬레이션 수를 말했는데 버튼 한 번은 5분만 넓혔다. 시뮬레이션을 버튼 한 번의 배율로 맞춰 고쳤다(`core.next_radius_factor`).
- #792: 추천이 후보 풀을 이미 반경 안에서만 가져와 깔때기의 「반경 밖 제거」가 늘 0이었다. 조언은 그 단계에서 5곳 이상 빠져야 반경 조언을 고르므로 실서버에서 반경 조언이 나올 수 없었다. 추천이 풀을 넓히기 상한(도보 30분)까지 가져오고 「반경 밖 제거」를 지금 반경으로 세도록 고쳤다(`recommend.core.pool_radius_factor`). 결과는 여전히 지금 반경 안에서만 나온다. 반경 테스트 둘은 일반 테스트가 됐다.

### 21.3 안전장치와 실패 처리

모델 출력이 화면까지 가는 길에서 거르는 곳을 순서대로 적는다.

| 단계 | 하는 일 | 코드 |
| --- | --- | --- |
| 입력 | 비공개 데이터(run, 후보, run의 근거 줄, 제외 목록)를 스냅샷, 도구 결과, 모델 입력에 넣지 않는다. 구성원은 별칭(m1, m2)으로만 간다 | agent/snapshot.py, agent/tools.py |
| 프롬프트 | 사유 글은 데이터일 뿐 지시로 따르지 않는다고 적고 지시문 예시를 넣는다 | llm/prompts.py |
| 도구 | 유형별 허용 목록, 진단 한 번에 5번(structure_reasons는 1번) 상한, 상한 뒤에는 도구를 닫고 답을 받는다. 모두 읽기 전용이다 | llm/service.py, agent/tools.py |
| 스키마 | 구조화 출력(strict)으로 받는다. 맞지 않으면 다시 묻지 않고 침묵한다(invalid_schema) | llm/client.py |
| 출력 검증 | 11.2의 단계: claim 대조, 슬롯 밖 숫자, 구성원 이름, 금지 표현, 사유 옮겨 쓰기, 허용된 버튼, 성립 | agent/core.py verify_diagnosis |
| 렌더 | 에이전트 문장과 구성원 글을 조각으로 나눈다. 인용은 검증한 범위만 quote 조각이고 금지 표현 검사는 text 조각에 건다. 알러지 사유는 인용하지 않는다. 지워진 핀과 반응을 가리키는 문장은 뺀다 | agent/core.py render_segments(#717) |
| 저장 | agent 테이블에는 사유 원문을 두지 않는다(reaction_id와 글자 수만) | agent/tools.py redact |
| 사람 | 버튼은 사람이 원래 하던 동작으로만 이어진다. 확정, 삭제, 조건 끄기는 버튼에 없다 | 16.3 |

실패하면 이렇게 된다.

- 모델 호출 실패와 시간 초과: 다시 묻지 않고 침묵한다. agent_runs에 outcome(model_failed, invalid_schema)과 이유가 남는다. 지도 제안 화면은 "지금은 따로 드릴 제안이 없어요"이고, 모델을 쓰지 않는 우리 조건 요약은 그대로 갱신된다.
- 검증 실패: 해당 claim, 문장, 버튼만 빠지고, 성립하지 않으면 침묵한다(invalid_claims).
- 관찰 도중 예외: outcome=error 한 행(단계, 예외 클래스 이름)을 남기고 30분, 2시간, 6시간 뒤에 다시 본다(#677, 12.2). 서버 로그도 클래스 이름만이다(#765).
- 조언 계산 실패: 500이고 FE는 조언 자리를 숨긴다(#750, 16.5).

### 21.4 테스트 지도

| 층 | 위치 | 보는 것 |
| --- | --- | --- |
| 단위(순수 함수) | backend/agent/tests/test_core_*.py | 탐지기 경계, 기준 시간, 정책, 우선순위, 검증, 조각 렌더, 요약 칸 나누기, 조언 고르기 |
| 조언 표 | backend/agent/tests/test_advice_cases.py | 깔때기와 근거 줄 상황별 조언 종류와 버튼 |
| 흐름(실제 DB) | backend/agent/tests/test_flows*.py, test_router.py | 관찰 루프, 커서와 lease, 저장 직전 재확인(stale), 동시 저장, 모델 호출 중 세션 없음, 권한, 비공개 데이터 유출 금지, 실패 기록 |
| llm 호출 | backend/llm/tests/test_agent_calls.py, test_failure_logging.py | 도구 상한, call_id, 실패 분류, 요청 모양, 로그에 사유 글 없음 |
| 평가셋(모델 없음) | backend/llm/tests/eval_agent/test_eval_cases.py | 평가셋이 지금 규칙과 맞는지 |
| 끝단 통합 | backend/integration/test_agent_e2e.py | 지도, 초대, 핀, 반응, 추천을 API로 만들고 관찰부터 수락까지, 추천부터 조언까지 끝까지 간다(모델만 대역). 모델 장애, 사유 속 지시문 인용, 반경 조언과 버튼 |
| 실제 모델 | backend/llm/tests/test_agent_live.py(`-m live`), run_eval.py | 키가 있을 때만 돈다. CI에서는 돌지 않는다 |

CI(backend-test)는 실제 모델 테스트를 뺀 전부를 PostgreSQL과 PostGIS 위에서 돌린다. 화면 테스트와 브라우저 끝단 테스트는 아직 없다. 에이전트 화면(#516, #536, #589)이 먼저다. QA 하네스를 실제 HTTP로 돌리는 일은 #788이다.
