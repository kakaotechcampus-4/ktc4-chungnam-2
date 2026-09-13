# API 계약 워크플로 — FE 병목 제거

목표: 프론트 담당자가 **백엔드 구현 완료를 기다리지 않고** `docs/api-spec.yaml`만으로 전 화면을 개발한다.

**구현 완료 (이슈 #38, 2026-09-02):** 아래 워크플로는 `contracts/` 패키지로 실제로 존재한다. 사용법은 `contracts/README.md` 참고 — 이 문서는 그 설계 배경만 남긴다.

## 1. 타입 생성

```bash
cd contracts && npm run gen:types   # docs/api-spec.yaml → contracts/src/types/api.d.ts
```
스펙이 바뀔 때마다 재실행. CI에 넣어 생성 결과가 커밋된 파일과 다르면 실패시킨다(스펙-코드 드리프트 방지) — #37(CI 이슈)에서 연동.

## 2. 목 서버

`contracts/mocks/`에 `msw`(Mock Service Worker) 핸들러가 `docs/api-spec.yaml`의 24개 경로 전부를 커버한다. 정적 픽스처가 아니라 **상태를 가진 인메모리 스토어**라 핀 찍기→반응→추천→게시→확정 흐름을 실제로 조작할 수 있다. 시나리오는 5개:

- `empty` — 6절 "핀이 하나도 없음"
- `happy-path`(기본값) — 기획안 6절 핵심 시나리오 그대로(로그인→핀→반응→추천→근거→게시→확정)
- `no-results` / `retry-limit` / `region-conflict` — `docs/errors.md`의 각 코드

프론트는 이 목 서버를 백엔드 대신 두고 개발한다. 실제 API가 준비되면 `worker.start()` 두 줄만 지우면 된다. `contracts/mocks/smoke.test.ts`가 6절 전체 흐름 + 4개 에러 시나리오를 자동 검증한다.

## 3. 검증

```bash
cd contracts
npm run lint:spec    # @redocly/cli lint docs/api-spec.yaml — 스펙 자체의 문법·스타일 검증
npm run typecheck    # tsc --noEmit — 핸들러가 생성된 타입과 어긋나지 않는지
npm test             # vitest — smoke.test.ts
```
백엔드 구현체는 별도로 계약 테스트(스펙과 실제 응답 스키마 비교)를 CI에 둔다 — `docs/architecture.md` 6절.

## 4. 스펙 변경 프로토콜 (구조 변경 즉시 보고)

1. `docs/api-spec.yaml` 수정 (루트 Claude Code 또는 승인된 변경만)
2. `docs/CHANGELOG-api.md`에 변경 내용·영향받는 엔드포인트·이유 기록
3. 프론트 담당자에게 즉시 통보 (변경 내용 + 마이그레이션 필요 여부)
4. 타입 재생성, 목 핸들러 갱신

**서브 디렉토리 Claude Code는 이 스펙을 읽기만 한다.** 구현 중 스펙이 부족하거나 잘못됐다고 판단되면 스펙을 직접 고치지 말고 루트에 보고한다 — `CLAUDE.md` 역할 분리 원칙.
