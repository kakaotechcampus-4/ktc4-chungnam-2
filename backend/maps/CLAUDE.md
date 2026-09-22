# backend/maps

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `backend/CLAUDE.md`(백엔드 공통), `docs/api-spec.yaml`(`/maps/*`, `/invites/*`), `docs/data-model.md`(`maps`, `memberships`, `invites`).

## 책임

- 지도 생성, 초대 링크 발급·수락, 구성원 목록·색 배정
- 구성원 수(N) 관리 — `recommend` 모듈의 5-4 임계값 계산이 이 값을 참조한다

## 하지 않는 것

- 권한 판정 (→ `authz`)
- 핀 데이터 (→ `pins`)

## 넘지 말 것

- `docs/permissions.md`의 역할·액션 목록(`invite.create` 포함)을 임의로 바꾸지 않는다 — 새 액션이 필요하면 루트에 보고 후 문서에 반영되면 구현한다(`authz/CLAUDE.md`와 같은 원칙).

## 완료 정의

- `/maps`, `/maps/{id}`, `/maps/{id}/invite`, `/invites/{token}/accept`, `/maps/{id}/members` 구현 + 단위 테스트
- 지도 생성 시 `seeding` 모듈에 프리시딩 잡을 큐잉하는 훅 호출(architecture.md 3절)은 이 모듈의 완료 조건에서 뺐다 — 그 잡의 지역은 "첫 핀 좌표로 확정"되는데 지도 생성 시점엔 핀이 0개라 트리거 시점 자체가 모순이었다(maps/for_Root.md 항목 2). 트리거를 어디로 옮길지(핀 생성 시점 등)는 `seeding` 모듈 착수 시 루트가 정한다.

## 코드 품질

`docs/code-quality.md` 참고.
