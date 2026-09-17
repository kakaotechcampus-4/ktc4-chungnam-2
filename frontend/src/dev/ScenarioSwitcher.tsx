import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { ScenarioName } from '@pingo/contracts/mocks/scenarios'

/** contracts/README.md §3. docs/errors.md 8개 화면 중 4개를 즉시 재현한다. */
const SCENARIOS: ScenarioName[] = [
  'happy-path',
  'empty',
  'no-results',
  'retry-limit',
  'region-conflict',
]

/**
 * 개발 전용 목 서버 시나리오 전환 버튼. App 에서 `import.meta.env.DEV` 로 감싸 렌더한다.
 * msw 를 정적 import 하지 않는 이유 — 그러면 프로덕션 번들에 목 서버가 딸려 들어간다.
 */
export default function ScenarioSwitcher() {
  const queryClient = useQueryClient()
  const [current, setCurrent] = useState<ScenarioName>('happy-path')
  const [failed, setFailed] = useState<string | null>(null)

  async function switchTo(name: ScenarioName) {
    setFailed(null)
    try {
      const { resetScenario } = await import('@pingo/contracts/mocks/browser')
      resetScenario(name)
      // 스토어가 통째로 갈렸으니 캐시도 버린다. invalidate 로는 이전 결과가 잠깐 남는다.
      await queryClient.resetQueries()
      setCurrent(name)
    } catch (err) {
      setFailed(name)
      console.error('[dev] 시나리오 전환 실패', err)
    }
  }

  return (
    <div className="fixed right-2 top-2 z-50 flex flex-wrap gap-1 rounded-md border bg-background/90 p-1 backdrop-blur">
      {SCENARIOS.map((name) => (
        <button
          key={name}
          type="button"
          onClick={() => void switchTo(name)}
          className={`rounded px-2 py-1 font-mono text-[10px] ${
            name === current ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'
          }`}
        >
          {name}
        </button>
      ))}
      {failed && <span className="px-2 py-1 text-[10px] text-destructive">{failed} 전환 실패</span>}
    </div>
  )
}
