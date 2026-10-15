"""v2 계획 보조 에이전트의 상수 — docs/agent-v2.md 5절 초기값 그대로. 조정 기준은 같은 문서 20절.

카테고리는 여기 두지 않는다. 관찰 대상은 `categories.pinnable()`, 추천 대상은 `categories.recommendable()`에서
꺼낸다(common/categories.py, #280).
"""

from datetime import timedelta

from common.settings import settings

TICK_INTERVAL_SEC = 300            # tick 주기
LEASE_SEC = 180                    # 관찰 lease
TICK_MAX_MAPS = 10                 # tick당 처리 지도 수 (초안, 측정 후 조정)
AGENT_LOOP_IN_PROCESS = settings.agent_loop_in_process   # 환경 변수 AGENT_LOOP_IN_PROCESS(기본 꺼짐, 12.1)

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
# 재시도 상한(attempt_no)은 개인 단위, 카테고리 무관, 5회다(#31). attempt_no로 세면 다른 카테고리 시도가 섞이고,
# 4회면 1회밖에 남지 않는다. 그래서 같은 카테고리 run 수를 따로 센다(GET /maps/{mapId}/runs의 기록, #469).

DIAGNOSIS_MAX_TOOL_CALLS = 5
STRUCTURE_REASONS_MAX_CALLS = 1
TOOL_RESULT_MAX_ITEMS = 30         # 초안

BACKOFF_HOURS = (2, 6, 24)         # 연속 닫힘 1회, 2회, 3회 이상
SUGGESTION_TTL = timedelta(hours=24)
AGENT_RUNS_RETENTION_DAYS = 30

MODEL_TYPES = ("stall", "split")
CODE_TYPES = ("no_reaction", "category_gap")
# shadow는 유형별이다(#531). 이 유형의 제안은 저장하되 화면과 이벤트로 내보내지 않는다. 명세 5절의 AGENT_SHADOW_MODE(bool)를
# 대신한다. 코드 유형은 M1-1(#531)부터 노출하고, 모델 유형은 평가 뒤(#534)에 이 목록에서 뺀다
SHADOW_DIAGNOSES = MODEL_TYPES

# 요약의 키 없는 사유 나누기 (8절). 값은 docs/constraints.md 칩 표를 따른다
NOT_FILTERED_CHIP_IDS = ("food_expensive", "cafe_expensive", "sight_expensive")   # 가격 키 없음 (#423)
SAFETY_WORDS = ("알러지", "알레르기")   # 초안. 이 낱말이 든 글은 "추천이 거르지 않아요" 칸으로
