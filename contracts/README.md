# @pingo/contracts

`docs/api-spec.yaml`(정본)에서 파생된 FE용 타입 + 목 서버. **백엔드 구현을 기다리지 않고 이 패키지만으로 전 화면을 개발**하는 게 목적이다.

## 설치

```bash
cd contracts
npm install
```

## 1. 타입 사용

```bash
npm run gen:types   # docs/api-spec.yaml → src/types/api.d.ts 재생성
```

스펙이 바뀔 때마다 다시 실행한다(`docs/CHANGELOG-api.md`에 변경이 기록되면 통보가 온다). FE 코드에서:

```ts
import type { components } from "@pingo/contracts/src/types/api";
type Pin = components["schemas"]["Pin"];
```

## 2. 목 서버 붙이기

브라우저(개발 서버)에서:

```ts
// main.tsx 같은 앱 진입점 최상단
if (import.meta.env.DEV) {
  const { worker } = await import("@pingo/contracts/mocks/browser");
  await worker.start({ onUnhandledRequest: "bypass" });
}
```

`worker`가 `*/auth/me`, `*/maps/:mapId/pins` 처럼 **와일드카드 오리진**으로 요청을 가로채므로, FE가 API 클라이언트에 어떤 `baseURL`을 쓰든(`http://localhost:8000`이든 상대경로든) 그대로 잡힌다. 실제 백엔드가 준비되면 이 두 줄만 지우면 된다.

테스트 코드(Vitest/Jest)에서는 `mocks/node.ts`의 `server`를 쓴다 — `contracts/mocks/smoke.test.ts`가 예시다.

## 3. 시나리오 전환

목 서버는 **정적 픽스처가 아니라 상태를 가진 인메모리 스토어**다. 핀을 찍으면 실제로 저장되고, 반응을 남기면 카운트가 바뀌고, 추천을 실행하면 결과가 쌓인다 — 기획안 6절 흐름을 그대로 조작해볼 수 있다.

기본값은 `happy-path`(음식점 카테고리가 추천 준비 완료 상태까지 미리 채워짐). `docs/errors.md`의 8개 화면 중 4개를 시나리오로 즉시 재현할 수 있다:

```ts
import { resetScenario } from "@pingo/contracts/mocks/browser"; // 또는 mocks/node

resetScenario("empty");            // "아직 아무도 핀을 찍지 않았어요"
resetScenario("happy-path");       // 기본값 — 추천 준비 완료 상태
resetScenario("no-results");       // "필터에 걸리는 핀이 없어요" (run_no_results)
resetScenario("retry-limit");      // "3번까지만 찾습니다" (run_retry_limit, attempt_no=3)
resetScenario("region-conflict");  // "두 조건을 동시에 만족하는 곳이 없어요" (run_region_conflict)
```

화면 개발 중 상태 전환 버튼을 하나 만들어 이 함수를 붙여두면 편하다.

## 4. 6절 워크스루 체크리스트

`mocks/smoke.test.ts`가 이 흐름을 코드로 검증한다. 화면을 만들 때 같은 순서로 확인하면 된다.

- [ ] 로그인 → `GET /auth/me`
- [ ] 핀 목록 → `GET /maps/map_1/pins` (시드: 흑돼지식당·우진해장국·카페 한라)
- [ ] 반대 반응에 사유 없이 등록 시도 → 422 `EVIDENCE_REQUIRED`
- [ ] 추천 준비 판정 → `GET /maps/map_1/recommend/readiness` (음식점은 이미 `ready: true`)
- [ ] run 생성 → `POST /maps/map_1/runs`
- [ ] 근거 확인 → `GET/PATCH /runs/{id}/evidence` (남의 줄은 `permissions.can_disable: false`)
- [ ] 지역 확인 → `POST /runs/{id}/regions/confirm`
- [ ] 실행 → `POST /runs/{id}/execute`
- [ ] 결과 3곳, 전부 `visibility: "private"` → `GET /runs/{id}/result`
- [ ] 게시 전엔 `GET /maps/map_1/pins`에 안 보임 → 게시 후 보임 → `POST /candidates/{id}/publish`
- [ ] 게시된 핀도 `checks` 유지 확인 (가드레일 5)
- [ ] 확정 리스트 추가 → `POST /maps/map_1/shortlist` (핀 `kind`가 `확정`으로 바뀜)
- [ ] 동선 조회 → `GET /maps/map_1/route`

## 참고

- `docs/api-spec.yaml` — 계약 정본
- `docs/errors.md` — 에러 코드 ↔ 화면 매핑
- `docs/permissions.md` — `permissions` 필드가 어떻게 계산되는지
- 스펙이 바뀌면 `docs/CHANGELOG-api.md`에 먼저 기록되고 통보된다 — 그때 `npm run gen:types` 재실행 + 이 패키지의 목 핸들러도 같이 갱신됨(루트 담당)
