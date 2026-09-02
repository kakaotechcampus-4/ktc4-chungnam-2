# backend/auth

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `docs/api-spec.yaml`(`/auth/*`), `docs/data-model.md`(`users`, `memberships` 중 `users`만 이 모듈 소유).

## 책임

- 카카오 OAuth 콜백 처리, httpOnly 쿠키 발급 (최종기획안 13절 — 토큰을 프론트에 두지 않는다)
- 로그인/로그아웃/탈퇴 API
- 탈퇴 시 연결된 사유·반응·근거 기록 삭제 (12절). **삭제 범위는 `pins.reactions`, `recommend.evidence_lines`를 포함하지만 이 모듈이 직접 그 테이블을 지우지 않는다** — 각 모듈에 삭제 콜백/이벤트를 요청하는 방식으로 구현할지는 구현 중 판단하되, 범위 자체(무엇을 지우는가)가 바뀌면 루트에 보고한다.

## 하지 않는 것

- 지도·구성원 권한 판정 (→ `authz`)
- 초대 링크 (→ `maps`)

## 넘지 말 것

- `memberships`, `maps` 테이블에 직접 쓰기 금지
- `docs/api-spec.yaml`의 `/auth/*` 경로 시그니처 변경 금지 — 부족하면 루트에 보고

## 완료 정의

- `docs/api-spec.yaml`의 `/auth/kakao/callback`, `/auth/me`, `/auth/logout`, `/auth/withdraw` 구현 + 단위 테스트
- 탈퇴 삭제 범위에 대한 테스트(연결 데이터가 실제로 지워지는지)

## 코드 품질

클린 코드 원칙·PR 리뷰 시 사람이 볼 지점은 `docs/code-quality.md` 참고. 이 모듈은 특히 "실패를 감추지 않는다"가 중요하다 — OAuth 콜백 실패를 조용히 로그인 성공처럼 처리하지 않는다.
