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
  // 접어 두면 지도 화면 상단 가운데 빈자리(‹와 프로필 사이)에 이름 하나만 보인다.
  const [open, setOpen] = useState(false)

  async function switchTo(name: ScenarioName) {
    setFailed(null)
    try {
      const { resetScenario } = await import('@pingo/contracts/mocks/browser')
      resetScenario(name)
      // 스토어가 통째로 갈렸으니 캐시도 버린다. invalidate 로는 이전 결과가 잠깐 남는다.
      await queryClient.resetQueries()
      setCurrent(name)
      setOpen(false)
    } catch (err) {
      setFailed(name)
      console.error('[dev] 시나리오 전환 실패', err)
    }
  }

  return (
    <div className="fixed left-1/2 top-3 z-50 flex max-w-[280px] -translate-x-1/2 flex-wrap justify-center gap-1 rounded-md border bg-background/90 p-1 backdrop-blur">
      {!open && (
        <button type="button" onClick={() => setOpen(true)} className="px-2 py-1 font-mono text-[0.625rem] text-muted-foreground">
          목 · {current} ▾
        </button>
      )}
      {open && SCENARIOS.map((name) => (
        <button
          key={name}
          type="button"
          onClick={() => void switchTo(name)}
          className={`rounded px-2 py-1 font-mono text-[0.625rem] ${
            name === current ? 'bg-primary text-primary-foreground' : 'text-muted-foreground'
          }`}
        >
          {name}
        </button>
      ))}
      {failed && <span className="px-2 py-1 text-[0.625rem] text-destructive">{failed} 전환 실패</span>}
    </div>
  )
}
