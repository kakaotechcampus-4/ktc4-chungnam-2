# backend/credits

크레딧 잔액과 원장. **명세 `docs/credits-reviews.md`를 먼저 읽는다(3, 6, 8, 12절).** 그다음 루트 문서: `/CLAUDE.md`,
`backend/CLAUDE.md`(백엔드 공통), `docs/api-spec.yaml`(credits 태그 — 정본, 명세와 다르면 이쪽을 따르고 루트에 보고),
`docs/data-model.md`(credits 절), `docs/errors.md`(`CREDIT_INSUFFICIENT`, `GUEST_NOT_ALLOWED`).

## 책임

- `credit_accounts`, `credit_ledger` 두 테이블(마이그레이션 0048). **원본은 원장이다.** `balance`는 원장 합을 담아 두는
  잠금용 값이고, 둘을 함께 바꾸는 곳은 `service._apply` 하나다
- 가격표와 지급량 — `constants.py` 한 곳(`INITIAL_CREDITS`, `PRICES`, `REVIEW_REWARD`)
- 게스트 판정 — `auth.api.guest_user_ids` 한 곳. 부르는 쪽이 `is_guest`를 넘기지 않는다
- `GET /credits/me`
- `api.py`: `check_can_spend`, `charge`, `refund`, `grant_review`, `get_balance`, `delete_by_user`, `reassign_user`
- 탈퇴 때는 남기고 7일 정리(`auth.service.purge_withdrawn_user`)에서 지운다 — 되살리면 잔액이 그대로다(#948)

## 하지 않는 것

- 다른 모듈의 실행을 막거나 세지 않는다. 기능마다 횟수 상한을 새로 두지 않는다(루트 CLAUDE.md "모델 호출 계량")
- 가격 숫자를 밖으로 흘리지 않는다. 다른 모듈은 `constants.py`를 import하지 않고(`integration/test_import_rules.py`),
  화면은 `GET /credits/me`로 받는다
- 커밋하지 않는다. 차감은 부르는 쪽의 실행 저장 트랜잭션에 얹힌다
- 페이즈 2 구매(`purchase`), 광고 충전(`ad`, `grant_ad`)은 미리 만들지 않는다(명세 3.3)

## 다른 모듈

`auth.api.guest_user_ids`만 부른다. 이 모듈을 부르는 곳은 `api.py` 머리 설명에 있다(recommend #949, agent.course #950,
reviews #951, auth의 7일 정리·합치기).

## 테스트

`credits/tests/`. 명세 12절 1~8. 커밋하는 테스트(동시 첫 차감)는 `committed_user`가 만든 사용자의 행만 끝나고 지운다.
