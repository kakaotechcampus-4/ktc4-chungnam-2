# backend/reviews

장소 후기(별점 + 글)와 신고. **명세 `docs/credits-reviews.md`를 먼저 읽는다(5, 6, 7, 8, 12절).** 그다음 루트 문서: `/CLAUDE.md`,
`backend/CLAUDE.md`(백엔드 공통), `docs/api-spec.yaml`(reviews 태그 — 정본, 명세와 다르면 이쪽을 따르고 루트에 보고),
`docs/data-model.md`(reviews 절), `docs/errors.md`(`PLACE_NOT_SUPPORTED`, `GUEST_NOT_ALLOWED`).

## 책임

- `reviews`, `review_reports` 두 테이블(마이그레이션 0049). 후기는 핀이 아니라 **자체 DB 장소(`places.id`)에 붙는다** — 같은
  장소의 후기는 어느 지도의 핀에서 봐도 같다
- 후기 규칙의 숫자 — `constants.py` 한 곳(`REVIEW_BODY_MAX`, 별점 범위, 쪽 크기). 화면은 `limits.body_max`로 받는다
- 엔드포인트 4개(`router.py`). 핀 경로는 `authz.guard`로 그 핀의 지도 구성원만(비구성원 404, 핀 조회와 같은 규칙,
  `loaders.py`). 장소는 `pins.api.get_pin_for_viewer`의 `place_id`, 실시간 핀은 422 `PLACE_NOT_SUPPORTED`(`core.place_of`)
- 신고는 「그 후기를 볼 수 있는 사람」만 — `pins.api.has_place_pin_on_member_map`. 숨김은 관리 스크립트로만(`scripts/`)
- `api.py`: `delete_reports_by_user`(탈퇴), `reassign_user`(게스트 합치기, no-op)

## 하지 않는 것

- 작성자 이름·id를 응답에 싣지 않는다(#432 결정 B). `is_mine`만. `auth.api.display_names`를 부르지 않는다
- 후기 글을 모델·추천·②·에이전트·로그로 보내지 않는다. `place_facts`를 바꾸지 않는다. 다른 모듈이 후기 글을 읽을 함수를 `api.py`에
  열지 않는다
- 게스트 판정, 보상 크레딧, 처음 지급량 숫자를 여기서 정하지 않는다 — `credits.api.reject_guest`, `grant_review`, `get_balance`
- 신고 수로 자동 숨기지 않는다(기준은 실제 데이터를 본 뒤, 명세 5절). 팔로우·댓글·좋아요·프로필·피드는 범위 밖(SNS, 결정 C)
- 커밋하지 않는다. 요청 세션(`session_scope`)이 한 번 커밋한다

## 다른 모듈

`pins.api.get_pin_for_viewer`, `pins.api.has_place_pin_on_member_map`, `credits.api.reject_guest`, `credits.api.grant_review`,
`credits.api.get_balance`, `places.api.get_places`(신고 목록 스크립트의 장소 이름)만 부른다. 이 모듈을 부르는 곳은 `auth.service`의
`WITHDRAW_STEPS`·`MERGE_STEPS`뿐이다.

## 정한 것 (명세에 없던 경우)

- 숨긴 후기를 작성자가 고쳐도(PUT) 숨김은 그대로다. 숨김을 푸는 길은 `scripts/hide.py --undo`뿐이다
- 숨긴 후기도 작성자는 지울 수 있다(DELETE 204). 지우고 다시 쓰면 새 후기라 숨김이 없다(보상은 원장 `ref_id`가 같아 0)
- 신고 오류 순서: 없거나 숨긴 후기·볼 수 없는 후기 404 → 게스트 403 → 내 후기 422. 핀 경로도 구성원 404 → 게스트 403 → 422 순이다

## 테스트

`reviews/tests/`. 명세 12절 17~24(`test_router.py`), 계정 수명(`test_account_lifecycle.py`), 관리 스크립트(`test_scripts.py`),
마이그레이션(`test_migration.py`). 요청 제약과 스펙의 일치는 `integration/test_request_constraints_match_spec.py`, 응답 모양은
`integration/test_response_contract.py`가 본다.
