# backend/maps

루트 문서를 먼저 읽는다: `/CLAUDE.md`, `docs/api-spec.yaml`(`/maps/*`, `/invites/*`), `docs/data-model.md`(`maps`, `memberships`, `invites`).

## 책임

- 지도 생성, 초대 링크 발급·수락, 구성원 목록·색 배정
- 구성원 수(N) 관리 — `recommend` 모듈의 5-4 임계값 계산이 이 값을 참조한다

## 하지 않는 것

- 권한 판정 (→ `authz`)
- 핀 데이터 (→ `pins`)

## 넘지 말 것

- 지도 생성 입력 필드(`region_hint` 등)는 `docs/data-model.md`에 "결정 이슈 미결"로 표시돼 있다. 필드를 임의로 확정하지 말고, 확정되면 루트가 스키마를 갱신한 뒤 반영한다.
- 구성원 색 팔레트·배정 주체도 미결이다 — 우선 `color: string`으로 받되 배정 로직을 임의로 짜지 말 것.

## 완료 정의

- `/maps`, `/maps/{id}`, `/maps/{id}/invite`, `/invites/{token}/accept`, `/maps/{id}/members` 구현 + 단위 테스트
- 지도 생성 시 `seeding` 모듈에 프리시딩 잡을 큐잉하는 훅 호출 (architecture.md 3절) — 실제 라벨링 로직은 `seeding`/`places` 담당, 이 모듈은 트리거만

## 코드 품질

`docs/code-quality.md` 참고.
