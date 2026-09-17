/**
 * contracts 의 목 서버(`contracts/mocks/*.ts`)에 대한 앰비언트 선언.
 *
 * 왜 실제 소스를 타입체크하지 않는가:
 * contracts 는 alias 로 물린 소스 전용 패키지라, 선언이 없으면 tsc 가 import 를 따라가
 * `contracts/mocks/*.ts` 전부를 **프론트의 strict 설정으로** 검사한다. 남의 패키지 소스가
 * 이쪽 빌드를 깨는 구조가 되고, contracts 를 고치는 건 루트 소관이라 이쪽에서 손댈 수도 없다.
 *
 * FE↔BE 계약의 정본은 `@pingo/contracts/src/types/api`(스펙에서 생성된 .d.ts)이고 그건 그대로
 * 타입체크된다. 목 서버는 계약이 아니라 개발 툴링이므로 쓰는 표면만 여기 적는다.
 * 원본: `contracts/mocks/browser.ts` · `contracts/mocks/scenarios.ts`
 */

declare module '@pingo/contracts/mocks/scenarios' {
  /** contracts/mocks/scenarios.ts 의 ScenarioName 과 같아야 한다. 늘어나면 여기도 추가. */
  export type ScenarioName =
    | 'empty'
    | 'happy-path'
    | 'no-results'
    | 'retry-limit'
    | 'region-conflict'
}

declare module '@pingo/contracts/mocks/browser' {
  import type { ScenarioName } from '@pingo/contracts/mocks/scenarios'

  export const worker: {
    start(options?: {
      onUnhandledRequest?: 'bypass' | 'warn' | 'error'
    }): Promise<ServiceWorkerRegistration | undefined>
    stop(): void
  }

  export function resetScenario(name: ScenarioName): void
  export type { ScenarioName }
}
