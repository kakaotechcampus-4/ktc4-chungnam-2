import { useId, type ReactNode } from 'react'
import { Check } from 'lucide-react'

import { isFull, percent, ProgressTrack } from './ProgressBar'
import Sentences from './Sentences'

export type TaskItem = { key: string; label: string; done: boolean; onClick?: () => void }

/**
 * 끝나지 않은 일의 카드(DESIGN.md 「끝나지 않은 일」, #1547). 「내가 남긴 의견 67%」 + 막대 + 할 일 목록 —
 * 얼마나 남았는지와 무엇이 남았는지를 함께 보이면 마저 끝내고 싶어진다(자이가르닉 효과).
 * 다 끝나면 부르는 쪽이 그리지 않는다. 할 일 표시라 브랜드 파랑이다(「파랑은 할 일」). 막대는 `ProgressTrack` 하나를 쓴다.
 * 목록 줄을 누르면 그 일로 바로 간다(`onClick`). 줄은 부르는 쪽이 고른 것만 — 길면 `more`로 나머지를 연다.
 */
export default function TaskProgress({
  title,
  done,
  total,
  unit,
  items,
  more,
  hint,
}: {
  title: string
  done: number
  total: number
  /** 숫자 뒤 단위(「곳」·「일」). */
  unit: string
  items: TaskItem[]
  more?: ReactNode
  hint?: string
}) {
  const id = useId()
  return (
    <section aria-labelledby={id} className="space-y-2.5 rounded-xl bg-surface p-3.5 ring-1 ring-ink-200">
      <div className="flex items-baseline justify-between gap-2">
        <p id={id} className="text-sm font-bold text-ink-900">
          {title}
          <span className="ml-1.5 text-base font-bold text-[var(--action-quiet-text)]">
            {done}/{total}
            {unit}
          </span>
        </p>
        <span aria-hidden="true" className={`text-sm font-bold ${isFull(done, total) ? 'text-[var(--good-text)]' : 'text-[var(--action-quiet-text)]'}`}>
          {percent(done, total)}%
        </span>
      </div>
      <ProgressTrack value={done} max={total} labelledBy={id} valueText={`${total}${unit} 중 ${done}${unit}`} />
      <ul className="space-y-0.5">
        {items.map((item) => (
          <li key={item.key}>
            <TaskRow item={item} />
          </li>
        ))}
      </ul>
      {(hint || more) && (
        <div className="flex items-end justify-between gap-2">
          {hint && (
            <p className="text-xs text-ink-500">
              <Sentences text={hint} />
            </p>
          )}
          {more}
        </div>
      )}
    </section>
  )
}

/** 할 일 한 줄 — 끝난 일은 채운 파란 원 + 체크, 남은 일은 빈 원. 누를 수 있으면 누르는 자리 전체가 44px다. */
function TaskRow({ item }: { item: TaskItem }) {
  const mark = item.done ? (
    // 끝나는 순간 원이 커지며 체크가 그려진다(`done-check`) — 다른 곳에서 넣어도 여기서 바로 보인다.
    <span className="done-check flex size-[18px] shrink-0 items-center justify-center rounded-full bg-[var(--action-fill)] text-white">
      <Check size={12} strokeWidth={3} aria-hidden="true" />
    </span>
  ) : (
    <span className="size-[18px] shrink-0 rounded-full border-[1.5px] border-ink-300 bg-surface" aria-hidden="true" />
  )
  const text = <span className={`min-w-0 flex-1 truncate ${item.done ? 'text-ink-500' : 'font-semibold text-ink-900'}`}>{item.label}</span>
  // 상태를 앞에 둔다 — 「성수 매운집 …」으로 시작하면 아래 핀 카드와 이름이 겹친다(화면 읽기·e2e).
  const state = <span className="sr-only">{item.done ? '끝난 일: ' : '남은 일: '}</span>
  if (!item.onClick) {
    return (
      <span className="flex min-h-8 items-center gap-2 text-body">
        {mark}
        {state}
        {text}
      </span>
    )
  }
  return (
    <button
      type="button"
      onClick={item.onClick}
      aria-label={`${item.done ? '끝난 일' : '남은 일'}: ${item.label}`}
      className="press hit-y-44 flex min-h-8 w-full items-center gap-2 rounded-md text-left text-body"
    >
      {mark}
      {text}
    </button>
  )
}
