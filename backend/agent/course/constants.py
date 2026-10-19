"""동선 에이전트 상수 초기값(명세 6절). 전부 초안이다 — 평가셋과 운영 기록을 보고 조정한다(명세 23절).

M0는 범위 B(순서 + 이동시간 검증)만 구현한다. 범위 A(시간 배정)의 상수는 결정(명세 2절) 뒤에 추가한다.
"""

COURSE_MODE = "B"
MIN_PLACES, MAX_PLACES = 2, 30

# 하드 판정
LEG_MAX_MIN = 40                   # 구간 하나의 도보 상한(분)
DAY_TRAVEL_MAX_MIN = 150           # 하루 도보 합계 상한(분)
# shortlist/routing.py의 DEFAULT_CLUSTER_THRESHOLD_M과 같은 값. 두 기준을 하나로 합치는 일은 #226/#274.
CLUSTER_THRESHOLD_M = 3_000

# 루프 상한
MAX_TURNS = 16
RUN_TIMEOUT_SEC = 180
MAX_INVALID_TURNS = 2              # 연속으로 쓸 수 없는 턴이 이만큼이면 이후는 기준선이 끝까지 간다
TOOL_LIMITS: dict[str, int] = {    # run당 도구별 상한. 없는 도구는 상한 없음(턴 상한만)
    "get_opening_hours": 6,
    "find_open_days": 6,
    "estimate_travel": 10,
    "try_move": 10,
}
MAX_LIVE_TRIALS = 3                # 채택하지 않은 시험을 동시에 들고 있을 수 있는 수
PLAN_MAX_STEPS = 5
LESSONS_KEEP = 5

# 모델 출력 (엘리스 비스트리밍 2000토큰 상한, #325)
THOUGHT_MAX_CHARS = 120

# 부드러운 목표
MEALS_PER_DAY_MAX = 2
MEAL_CATEGORY = "음식점"
CAFE_CATEGORY = "카페"
TOUR_CATEGORY = "관광지"
NIGHT_LABEL = "night_view"

# 화면 문장에 쓰면 안 되는 표현(초안). 결정을 지시하는 말을 막는다.
FORBIDDEN_PHRASES = ("빼세요", "삭제하세요", "확정하세요", "여기로 가세요", "포기하세요")
