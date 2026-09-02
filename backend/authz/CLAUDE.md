# backend/authz

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/permissions.md`(정본), `docs/api-spec.yaml`의 `Permissions` 스키마.

## 책임

- `docs/permissions.md`에 선언된 롤(`member`/`author`/`owner`) → (범위, 액션) 판정 엔진
- 모든 리소스 응답에 `permissions` 객체를 계산해 주입하는 공통 유틸 제공 (다른 모듈이 이 유틸을 호출)

## 하지 않는 것

- 실제 액션 실행(핀 생성, 반응 등록 등)은 각 리소스 모듈이 한다. 이 모듈은 "할 수 있는가"만 답한다.

## 넘지 말 것

- **`docs/permissions.md`의 역할·범위·액션 목록을 임의로 바꾸지 않는다.** 새 액션이 필요하면(예: v2의 `member.kick`) 루트에 보고 후 문서에 반영되면 구현한다.
- 특정 모듈에 하드코딩된 권한 if문을 심지 않는다 — 반드시 이 모듈의 판정 함수를 거치게 한다. 다른 모듈에서 권한 로직을 재구현하는 순간 이 모듈을 둔 의미가 없어진다.

## 완료 정의

- `can(user, action, resource) -> bool` 판정 함수 + 단위 테스트 (역할별·범위별 케이스 전부)
- `docs/permissions.md`의 "15-1 표와의 매핑" 절 4개 행이 전부 테스트로 커버됨

## 코드 품질

`docs/code-quality.md` 참고. 이 모듈은 권한 판정 로직이라 리뷰 우선순위가 가장 높다 — 범위·경계 준수를 특히 꼼꼼히 본다.
