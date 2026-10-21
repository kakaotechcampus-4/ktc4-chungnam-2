"""동선 에이전트 상수 초기값(명세 6절). 전부 초안이다 — 평가셋과 운영 기록을 보고 조정한다(명세 23절).

M0는 범위 B(순서 + 이동시간 검증)만 구현한다. 범위 A(시간 배정)의 상수는 결정(명세 2절) 뒤에 추가한다.
"""

COURSE_MODE = "B"
MIN_PLACES, MAX_PLACES = 2, 30

# 이동 방식(초안 — 직선거리만 아는 거친 추정이라 화면에는 늘 "약"으로 쓴다. 평가셋과 운영 기록을 보고 조정한다)
# 직선거리가 WALK_MAX_M 이하인 구간은 걷고(분은 common.geo.approx_walk_minutes), 넘으면 대중교통을 탄다.
# 대중교통 분 = 직선거리 / TRANSIT_SPEED_M_PER_MIN + TRANSIT_OVERHEAD_MIN. 속도 약 20km/h는 서울 지하철·버스의 평균 표정속도(약 30km/h 안팎)에
# 직선이 아닌 노선(우회·환승)을 감안해 보수적으로 낮춘 값이고, 10분은 걸어서 타고 내리는 시간·대기·환승을 뭉친 값이다.
WALK_MAX_M = 2_000                 # 이 거리 이하는 도보 구간(약 25분)
TRANSIT_SPEED_M_PER_MIN = 333      # 약 20km/h
TRANSIT_OVERHEAD_MIN = 10
MODE_WALK, MODE_TRANSIT = "walk", "transit"

# 하드 판정
LEG_MAX_MIN = 40                   # 도보 구간 하나의 상한(분). 대중교통 구간에는 적용하지 않는다
DAY_WALK_MAX_MIN = 150             # 하루 도보 합계 상한(분). 구성원 daily_walk_max도 도보 분에만 건다
DAY_TRAVEL_MAX_MIN = 180           # 하루 이동 합계 상한(분, 도보+대중교통). 하루를 넘기지 않는 하드 한계
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
# day_has(day, tag): 그날 코스에 그 라벨이 참인 장소가 하나 이상. tag → (장소 라벨 키, 화면에 쓰는 말). 전부 docs/constraints.md 관광지 라벨이고
# 서비스가 Place.labels로 읽는 키(confidence=known, value=true)다. 모델은 이 tag 이름만 고르고, 이 밖의 말은 unmatched다.
DAY_HAS_TAGS: dict[str, tuple[str, str]] = {
    "performance": ("performance", "공연"),
    "exhibition": ("exhibition", "전시"),
    "night_view": ("night_view", "야경"),
    "indoor": ("is_indoor", "실내"),
    "shopping": ("shopping", "시장·쇼핑"),
    "walkable": ("walkable", "산책"),
    "kid_friendly": ("kid_friendly", "아이와 가기 좋은"),
    "heritage": ("heritage_tour", "고궁·유적"),
}
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
