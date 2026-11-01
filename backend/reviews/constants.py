"""장소 후기 정책 값(docs/credits-reviews.md 5절, 7절, #432). 후기 규칙의 숫자를 정하는 곳은 여기 하나다.

화면은 `ReviewPage.limits.body_max`로 받고 숫자를 적지 않는다(#733). 보상 크레딧(10)과 게스트 안내의 처음 지급량(30)은 credits가
정한다 — 여기 적지 않는다. 값을 바꾸면 명세 5절 표, docs/api-spec.yaml ReviewUpsertRequest, 다음 마이그레이션의 CHECK를 같이 고친다.
"""

REVIEW_BODY_MAX = 500   # 앞뒤 공백을 걷은 뒤 글 길이 상한(자). reviews.body CHECK와 같다
RATING_MIN, RATING_MAX = 1, 5
PAGE_SIZE = 20   # GET /pins/{pinId}/reviews 한 쪽
