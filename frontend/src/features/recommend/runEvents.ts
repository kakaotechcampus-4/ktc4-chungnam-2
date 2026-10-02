import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { isPageLeaving } from '@/features/map/realtime'

import { useAiStore } from './aiStore'
import { recommendKeys } from './queries'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/**
 * 개인 채널(docs/events.md) — 내 run 의 진행 단계·후보 준비·실패. 본인의 비공개 후보는 이 채널로만 온다(5-5-1).
 * 이벤트가 안 와도 결과 조회가 2초마다 확인하므로(useResultQuery) 연결이 끊겨도 화면이 멈추지 않는다.
 */
export function useRunEvents(mapId: string, runId: string | undefined) {
  const queryClient = useQueryClient()
  const [steps, setSteps] = useState<{ step: number; label: string }[]>([])

  useEffect(() => {
    if (!runId) return
    const source = new EventSource(`${BASE_URL}/maps/${mapId}/events/me`, { withCredentials: true })
    const mine = (e: MessageEvent) => {
      const data = JSON.parse(e.data) as { run_id: string; step?: number; label?: string }
      return data.run_id === runId ? data : null
    }
    const finish = (status: 'done' | 'failed') => {
      const run = useAiStore.getState().runs[mapId]
      if (run?.id === runId) useAiStore.getState().setRun(mapId, { ...run, status })
      void queryClient.invalidateQueries({ queryKey: recommendKeys.result(runId) })
    }
    source.addEventListener('run.progress', (e) => {
      const d = mine(e)
      // 같은 단계가 두 번 와도(at-least-once) 한 줄만 둔다.
      if (d?.step) setSteps((s) => [...s.filter((x) => x.step !== d.step), { step: d.step!, label: d.label ?? '' }].sort((a, b) => a.step - b.step))
    })
    source.addEventListener('run.candidates_ready', (e) => mine(e) && finish('done'))
    source.addEventListener('run.failed', (e) => mine(e) && finish('failed'))
    source.onerror = () => {
      if (!isPageLeaving() && source.readyState === EventSource.CLOSED) console.error('[realtime] 개인 채널이 닫혔어요 — 결과는 조회로 계속 확인해요', mapId)
    }
    return () => source.close()
  }, [mapId, runId, queryClient])

  return steps
}
