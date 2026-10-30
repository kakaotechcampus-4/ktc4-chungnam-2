import { useEffect } from 'react'

import { useRouteStore } from '@/features/shortlist/routeStore'

import { useCourseMapStore } from './courseMapStore'

/**
 * 확정 탭 머리에 붙는 AI 코스 범례(#683) — 지도에 그린 날짜별 선 모양과 「끄기」.
 * 「동선 보기」와 같은 자리에 선을 그어서 둘은 함께 켜지지 않는다. 동선 보기를 켜면 코스는 꺼진다.
 */
export default function CourseMapLegend({ mapId }: { mapId: string }) {
  const { mapId: shownOn, days, hide } = useCourseMapStore()
  const routeOn = useRouteStore((s) => s.on)
  const shown = shownOn === mapId && days.length > 0

  useEffect(() => {
    if (routeOn && shown) hide()
  }, [routeOn, shown, hide])

  if (!shown || routeOn) return null
  return (
    <div className="mt-2 flex items-start gap-2 rounded-xl bg-white p-2.5 ring-1 ring-ink-200">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-ink-900">AI 코스를 지도에 보여 주고 있어요</p>
        <ul aria-label="날짜별 선" className="mt-1 flex flex-wrap gap-x-3 gap-y-1">
          {days.map((d) => (
            <li key={d.title} className="flex items-center gap-1.5 text-xs text-ink-700">
              <svg width="24" height="6" aria-hidden="true" className="shrink-0">
                <line x1="0" y1="3" x2="24" y2="3" stroke={`var(${d.color})`} strokeWidth="3" strokeDasharray={d.dash || undefined} />
              </svg>
              {d.title}
            </li>
          ))}
        </ul>
      </div>
      <button type="button" onClick={hide} className="btn-neutral btn-sm shrink-0">
        끄기
      </button>
    </div>
  )
}
