import { useEffect, useRef } from 'react'

import { markTabNews } from '@/features/shell/tabNews'

import { useCourseViewStore } from './courseMapStore'
import { isFinished } from './model'
import { useCourseRunQuery } from './queries'

/**
 * 짜는 중인 AI 코스를 지도 화면 어디서든 지켜본다(#1719). 코스 화면이 닫히면 그 화면의 진행 조회가 멈춰서,
 * 다른 탭에 가 있으면 다 짰는지 알 길이 없었다. 같은 조회(같은 캐시)를 여기서 이어 돌리므로 두 번 부르지 않는다.
 * 진행 중에서 끝남으로 바뀌는 순간 AI 코스 탭에 새 소식을 단다(보고 있는 탭이면 `markTabNews`가 달지 않는다).
 * 처음 받았을 때 이미 끝나 있던 코스(예전 코스 다시 열기)에는 달지 않는다.
 */
export default function CourseRunWatcher({ mapId }: { mapId: string }) {
  const runId = useCourseViewStore((s) => s.runs[mapId]?.runId)
  return runId ? <Watch key={runId} mapId={mapId} runId={runId} /> : null
}

function Watch({ mapId, runId }: { mapId: string; runId: string }) {
  const run = useCourseRunQuery(runId).data
  const before = useRef(run?.status)
  useEffect(() => {
    const was = before.current
    before.current = run?.status
    if (!run || !isFinished(run) || was === undefined || isFinished({ status: was })) return
    markTabNews(mapId, 'course', run.status === 'done' ? 'AI 코스가 완성됐어요' : 'AI 코스를 짜지 못했어요')
  }, [run, mapId])
  return null
}
