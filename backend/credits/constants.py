"""크레딧 가격표와 지급량(docs/credits-reviews.md 3.1, 3.2절, #432). 가격을 정하는 곳은 여기 하나다.

다른 모듈은 이 파일을 import하지 않는다(integration/test_import_rules.py가 막는다). 실행을 하는 모듈은 `credits.api.charge`
(feature=...)만 부르고, 화면은 `GET /credits/me`로 값을 받는다. 값을 바꾸면 명세 3절 표도 같이 고친다.
"""

INITIAL_CREDITS = 30   # 정식 계정이 처음 받는 크레딧. 계정 행은 처음 쓰기 때 만든다

# 1크레딧이 감싸는 모델 원가(원). 가격은 이 단가에서 나온다 — 기능 1번의 평균 원가(딸린 「+」·백그라운드 몫 포함)를
# 이 값으로 나눠 올림한 수(명세 3.2, 결정 #1478). 단가를 바꾸면 PRICES와 명세 3.2 표를 같이 다시 정한다.
CREDIT_COST_KRW = 1

# feature(= llm_calls.feature 라벨) -> 실행 1번에 빠지는 크레딧. 산정과 환불 조건은 명세 3.2 표(검사가 이 dict와 맞춘다).
# 표에 없는 feature는 크레딧을 쓰지 않는다
# (「+」 근거 추가 evidence_add, 백그라운드 agent_diagnose·agent_summary — 부르는 쪽이 charge를 부르지 않는다).
PRICES: dict[str, int] = {
    "recommend_run": 1,   # 「추천 받기」 POST /maps/{mapId}/runs. 다시 찾기·근거 고치기는 0
    "course": 1,          # 「AI 코스 짜기」 POST /maps/{mapId}/courses
}

REVIEW_REWARD = 10   # 장소 후기를 그 장소에 처음 쓸 때. 후기 수 제한 없음, 별점과 무관. MAX_BALANCE까지만 채운다

# 잔액 상한(명세 3.6절, #981). 후기 보상과 환불은 여기까지만 채운다(core.capped_gain). 이미 넘은 잔액은 깎지 않는다.
MAX_BALANCE = 30

# 광고 보고 충전(명세 3.7절, #1037). 값을 바꾸면 3.7절 표도 같이 고친다.
AD_REWARD = 10           # 1회 보상. 잔액 상한까지만 채운다(core.capped_gain, 3.6)
AD_DAILY_MAX = 3         # 사람당 KST 하루 세션 수. 세션을 열 때 센다
AD_MIN_WATCH_S = 7       # 세션을 연 뒤 이만큼(초) 지나야 받을 수 있다
AD_SESSION_TTL_S = 900   # 연 세션은 이 안(초)에 받아야 한다
