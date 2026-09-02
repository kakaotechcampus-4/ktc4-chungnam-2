# backend/pins

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `docs/api-spec.yaml`(`/maps/{id}/pins`, `/maps/{id}/counts`, `/pins/*`), `docs/data-model.md`(`pins`, `reactions`, `shortlist_items`).

## 책임

- 핀 CRUD (링크·검색·좌표 3경로), 중복 판정
- 반응(♥/△/🚫/?) 등록·수정·삭제, 반대 시 사유 필수 검증 (가드레일 3)
- 분류×종류 이중 필터 집계 (`GET /maps/{id}/counts`)
- 핀 `visibility`(public/private) 필터링 — 비공개 AI 후보는 요청자 본인에게만 내려준다 (5-5-1)

## 하지 않는 것

- 추천 로직 자체 (→ `recommend`). 이 모듈은 `recommend`가 만든 후보를 게시할 때 `pins` 테이블에 쓰는 쪽만 담당.
- 장소 사실 데이터 라벨링 (→ `places`). `pins`는 `places.id`만 참조한다.

## 넘지 말 것

- 중복 핀 "같은 곳" 판정 기준은 `docs/data-model.md`에 미결로 표시돼 있다. 구현 편의로 임의 기준(예: 좌표 완전 일치)을 정하지 말고 루트에 확인 요청.
- 핀 삭제 권한 규정도 미결이다 — 구현 전 루트 확인.
- `docs/constraints.md`의 실격 조건 값을 이 모듈에서 참조는 하되 수정하지 않는다.

## 완료 정의

- `docs/api-spec.yaml` `pins` 태그 전 엔드포인트 구현 + 단위 테스트
- 반대 반응에 사유 없이 등록 시도 시 422 `EVIDENCE_REQUIRED` 반환 테스트 (`docs/errors.md`)
- 게시된 AI 핀 상세에서 `checks` 배열이 유지되는지 테스트 (가드레일 5)

## 코드 품질

`docs/code-quality.md` 참고. `visibility` 필터링(5-5-1)은 특히 꼼꼼히 — 다른 사람의 비공개 후보가 새면 가드레일 1 위반이다.
