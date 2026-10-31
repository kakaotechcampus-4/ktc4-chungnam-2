"""크레딧 가격표와 지급량(docs/credits-reviews.md 3.1, 3.2절, #432). 가격을 정하는 곳은 여기 하나다.

다른 모듈은 이 파일을 import하지 않는다(integration/test_import_rules.py가 막는다). 실행을 하는 모듈은 `credits.api.charge`
(feature=...)만 부르고, 화면은 `GET /credits/me`로 값을 받는다. 값을 바꾸면 명세 3절 표도 같이 고친다.
"""

INITIAL_CREDITS = 30   # 정식 계정이 처음 받는 크레딧. 계정 행은 처음 쓰기 때 만든다

# feature(= llm_calls.feature 라벨) -> 실행 1번에 빠지는 크레딧. 표에 없는 feature는 크레딧을 쓰지 않는다
# (「+」 근거 추가 evidence_add, 백그라운드 agent_diagnose·agent_summary — 부르는 쪽이 charge를 부르지 않는다).
PRICES: dict[str, int] = {
    "recommend_run": 1,   # 「추천 받기」 POST /maps/{mapId}/runs. 다시 찾기·근거 고치기는 0
    "course": 1,          # 「AI 코스 짜기」 POST /maps/{mapId}/courses
}

REVIEW_REWARD = 10   # 장소 후기를 그 장소에 처음 쓸 때. 상한 없음, 별점과 무관
