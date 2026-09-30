"""backend/llm 모델 호출 3곳의 프롬프트 본문.

모델 확정(#12) 이후 실제 프롬프트로 채우는 자리(backend/llm/CLAUDE.md "우선순위" 절,
PR #44 리뷰 반영). service.py의 각 함수가 모델을 실제로 호출하게 되면 여기 상수를
그대로 시스템/유저 프롬프트로 사용한다.
"""

RANK_CANDIDATES_PROMPT = """너는 이미 실격 필터를 통과한 후보들만 받는다.
이 후보 목록을 다시 거르거나 줄이지 않는다. 아래 고정된 배점 규칙에 따라
점수를 계산하고 순위를 매긴 뒤, 각 인원에게 보여줄 짧은 코멘트도 작성한다.

## 배점 규칙 (반드시 이 값을 그대로 사용, 임의로 바꾸지 않는다)
- quiet: 3점
- wait_short: 2점
- comfortable_seat: 2점
- local_flavor: 2점
같은 태그를 여러 명이 언급했으면 인원수만큼 곱하되, 한 태그당 최대 3배까지만
인정한다.

## 출력 규칙
1. 입력받은 후보 집합을 그대로 유지한다 — 후보를 추가하거나 빼지 않는다.
2. 위 배점 규칙으로 계산한 점수가 높은 순서대로 rank를 1부터 매긴다(중복 없이).
3. member_comment는 그 사람이 실제로 남긴 선호 문장에 근거가 있을 때만
   작성한다. 근거가 없으면 반드시 null이다.
4. 반드시 JSON으로만 응답한다.
   형식: {"ranked": [{"place_id": "...", "rank": ..., "member_comment": "..." 또는 null}]}
"""


PLAN_EVIDENCE_PROMPT = """너는 여행 그룹 구성원이 남긴 사유(자유 텍스트)를 구조화한다.
입력은 JSON 배열이고, 각 원소는 index·text·badge·fact_key를 가진다.

## 출력 규칙
1. evidence_lines는 입력과 같은 개수, 같은 순서로 내놓는다. 원소를 추가하거나 빼지 않는다.
2. 각 원소의 text는 입력 text를 글자 그대로 복사한다. 고치거나 요약하지 않는다.
3. fact_key는 사유가 아래 목록 중 하나를 명확하게 가리킬 때만 채운다.
   확실하지 않으면 null이다. 목록에 없는 값은 쓰지 않는다.
   contains_shellfish, spicy_focused, oily_focused, price_bucket, capacity_min,
   is_crowded_large, wait_short, quiet, comfortable_seat, local_flavor
4. 입력에 fact_key가 이미 있으면 그대로 둔다.
5. badge는 입력 값을 그대로 쓴다. 사유가 반드시 지켜야 하는 조건(알레르기 등)으로
   읽히면 required로 올릴 수는 있지만, 낮추지는 않는다.
6. circle_radius_m은 사유에 "도보 10분", "500m"처럼 거리가 수치로 적힌 경우에만
   미터 단위 정수로 채운다. 그 외에는 null이다.
7. source는 입력 그대로, 나머지 필드는 null로 둔다.
8. 반드시 지정된 JSON 스키마로만 응답한다.
"""
