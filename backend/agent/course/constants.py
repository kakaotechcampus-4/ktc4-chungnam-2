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

# 요청 목표(명세 8.2). 점수는 코드가 계산하고 모델은 쓰지 않는다
REQUEST_TEXT_MAX_CHARS = 100
GOALS_MAX = 4
INDOOR_LABEL = "is_indoor"
INDOOR_MET_RATIO = 0.7             # day_indoor: 라벨을 아는 장소 중 실내 비율이 이 이상이면 충족
DAILY_WALK_LOW_MAX_MIN = 60        # daily_walk_low: 하루 도보 합계의 최대가 이 이하면 충족
# 지휘 턴(pivot 3절)
DIRECT_MAX_TURNS = 5
CANDIDATES_MAX = 3
ASK_MAX = 2
CLIMB_MAX_STEPS = 60               # optimize 한 번이 채택하는 수리의 최대 수

# 서비스 경로(AI 코스 짜기 API, #334 — 팀 결정 #580 전 브랜치 초안). 전부 초안이다
COURSE_DAILY_LIMIT = 5             # 사용자당 하루 요청 수. 하루 = KST 자정에 초기화
COURSE_DAY_BOUNDARY_TZ = "Asia/Seoul"
COURSE_DAYS_MAX = 14               # 한 번에 짜는 여행 날짜 수 상한(지도 기간이 더 길면 앞 14일만)
MEMBER_WALK_MIN, MEMBER_WALK_MAX = 10, 480   # member_constraints.daily_walk_max의 값(분) 범위
EXCLUDED_OVER_LIMIT = "OVER_LIMIT"
EXCLUDED_OVER_LIMIT_MESSAGE = f"한 번에 짤 수 있는 {MAX_PLACES}곳을 넘어 동선에서 빠졌어요"
