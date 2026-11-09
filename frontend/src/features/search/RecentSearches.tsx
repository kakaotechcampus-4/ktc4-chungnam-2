import { Clock, X } from 'lucide-react'

/**
 * 검색창 아래 「최근 검색」(검색창에 포커스가 있고 비어 있을 때). 누르면 그 검색어로 바로 찾는다.
 * 검색창과 붙어 한 덩어리다 — 검색창 쪽 모양(아래 모서리 펴기)은 MapLayout 이 같이 바꾼다.
 * 목록을 누르는 동안 입력칸 포커스를 뺏지 않는다(onMouseDown) — Safari는 버튼을 눌러도 포커스를 옮기지 않아,
 * 그대로 두면 blur로 목록이 먼저 닫혀 누른 것이 사라진다.
 */
export default function RecentSearches({
  list,
  floating,
  onPick,
  onRemove,
  onClear,
}: {
  list: string[]
  floating: boolean
  onPick: (q: string) => void
  onRemove: (q: string) => void
  onClear: () => void
}) {
  return (
    <div
      onMouseDown={(e) => e.preventDefault()}
      // 검색창 바로 밑에 붙어 한 덩어리로 보인다(검색창이 아래 모서리를 편다). 지도 위에서는 그림자가 위로 번져 이음매를 덮지 않게 위쪽을 자른다.
      className={`absolute inset-x-0 top-full z-30 rounded-b-xl border border-t-0 border-brand-600 bg-surface pb-2 pt-1 ${floating ? 'pointer-events-auto shadow-float [clip-path:inset(0_-12px_-12px_-12px)]' : ''}`}
    >
      <div className="flex items-center justify-between px-4 pb-1">
        <h2 className="text-xs font-semibold text-ink-500">최근 검색</h2>
        <button type="button" onClick={onClear} className="btn-text text-xs">
          전체 삭제
        </button>
      </div>
      <ul>
        {list.map((q) => (
          <li key={q} className="flex items-center">
            <button type="button" onClick={() => onPick(q)} className="flex min-h-11 min-w-0 flex-1 items-center gap-2 px-4 text-left text-body text-ink-900 hover:bg-ink-50">
              <Clock size={16} aria-hidden="true" className="shrink-0 text-ink-400" />
              <span className="truncate">{q}</span>
            </button>
            <button type="button" aria-label={`${q} 검색 기록 지우기`} onClick={() => onRemove(q)} className="flex size-11 shrink-0 items-center justify-center text-ink-500 hover:text-ink-900">
              <X size={16} aria-hidden="true" />
            </button>
          </li>
        ))}
      </ul>
    </div>
  )
}
