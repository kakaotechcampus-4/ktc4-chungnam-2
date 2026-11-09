import { useCourseMapStore } from './courseMapStore'
import Sentences from '@/ui/Sentences'

/**
 * AI 코스 탭 머리에 붙는 범례(#683) — 지도에 그린 날짜별 선 모양과 「끄기」.
 * 코스 선은 AI 코스 탭에서만, 「동선 보기」 선은 확정 탭에서만 그려서 둘은 한 화면에 겹치지 않는다.
 */
export default function CourseMapLegend({ mapId }: { mapId: string }) {
  const { mapId: shownOn, days, hide } = useCourseMapStore()
  const shown = shownOn === mapId && days.length > 0

  if (!shown) return null
  return (
    <div className="mt-2 flex items-start gap-2 rounded-xl bg-surface p-2.5 ring-1 ring-ink-200">
      <div className="min-w-0 flex-1">
        <p className="text-xs font-semibold text-ink-900"><Sentences text="AI 코스를 지도에 보여 주고 있어요" /></p>
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
