# API 스펙 변경 이력

`docs/api-spec.yaml`이 바뀔 때마다 여기 기록한다. 프론트 담당자는 이 파일을 구독해서 변경을 즉시 확인한다.

## 2026-09-02 (2) — 목 서버 구축 + 스펙 오류 수정 (이슈 #38)

- `contracts/` 패키지 신설: `openapi-typescript` 타입 생성 + `msw` 목 서버(24개 경로 전부, 상태를 가진 인메모리 스토어) + 시나리오 5종. 사용법은 `contracts/README.md`.
- **`docs/api-spec.yaml` 자체 오류 수정** (`@redocly/cli lint` 통과 확인, 이전엔 25개 에러로 무효한 스펙이었음):
  - `nullable: true`(OAS 3.0 문법)를 OAS 3.1 문법인 `type: [T, "null"]`로 4곳 수정 (`Pin.source_run_id`, `EvidenceLine.fact_key`, `Candidate.published_pin_id`, `ShortlistItem.visit_order`)
  - 응답 객체에 `description` 누락 18곳 보강
  - operation `summary` 누락 3곳 보강 (`POST /auth/logout`, `GET /maps/{mapId}`, `GET /maps/{mapId}/shortlist`)
  - `Pin` 스키마에 `price_bucket` 필드 추가 (미사용 컴포넌트였던 `PriceBucket`을 실제로 연결)
- **프론트 영향**: 타입을 재생성해야 한다(`npm run gen:types`). `Pin.source_run_id` 등 4개 필드의 TS 타입이 `string | null`(과거엔 사실상 `string`으로만 추론됨)로 바뀐다 — null 체크 추가 필요.

## 2026-09-02 (1) — 초기 계약 확정

- `docs/api-spec.yaml` 최초 작성. `최종기획안.md` 4·5·6절 + 기술 멘토링 피드백 기반.
- 확정 사항: `PlaceSource` 어댑터 추상화(D1), `place_facts` 자체 DB(D2), 프리시딩(D3), `unknown_policy` 차등(D4), 동선 v1 유지/카톡파싱 v2(D5), SSE 확정(D6).
- 프론트 영향: 전 엔드포인트가 신규. `docs/openapi-workflow.md`대로 타입 생성 + 목 서버 세팅부터 시작하면 됨.
- 열린 항목(스펙에 자리만 잡아둔 값 — 결정되는 대로 갱신): 지도 생성 입력 필드, 중복 핀 판정 기준, 재시도 3회 상한 집계 단위, N의 정의, 구성원 색 배정 방식, 화면 구조(데스크톱 vs 모바일 — 응답 형태 자체엔 영향 적음).
