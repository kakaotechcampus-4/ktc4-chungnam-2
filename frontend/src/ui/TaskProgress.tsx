import type { ReactNode } from 'react'

import Sentences from './Sentences'

/**
 * 끝나지 않은 일의 진행 막대(DESIGN.md 「진행 막대」, #1547). 「내 의견 3/5곳」처럼 얼마나 남았는지 보여 주면
 * 마저 끝내고 싶어진다(자이가르닉 효과). 다 끝나면 부르는 쪽이 그리지 않는다 — 칭찬 배너를 따로 두지 않는다.
 * 할 일 표시라 브랜드 파랑이다(「파랑은 할 일」 규칙). 남은 일로 바로 가는 `action`은 글자 버튼 하나다.
 */
export default function TaskProgress({
  label,
  done,
  total,
  unit,
  hint,
  action,
}: {
  label: string
  done: number
  total: number
  /** 숫자 뒤 단위(「곳」·「일」). */
  unit: string
  hint?: string
  action?: ReactNode
}) {
  const percent = total > 0 ? Math.round((done / total) * 100) : 0
  return (
    <section aria-label={`${label} 진행`} className="space-y-2 rounded-xl bg-surface p-3 ring-1 ring-ink-200">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-bold text-ink-900">
          {label}{' '}
          <span className="text-[var(--action-quiet-text)]">
            {done}/{total}
            {unit}
          </span>
        </p>
        {action}
      </div>
      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={done}
        aria-valuetext={`${total}${unit} 중 ${done}${unit}`}
        className="h-1.5 overflow-hidden rounded-full bg-[var(--selected-bg)]"
      >
        <div className="h-full rounded-full bg-[var(--action-fill)] transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${percent}%` }} />
      </div>
      {hint && (
        <p className="text-xs text-ink-500">
          <Sentences text={hint} />
        </p>
      )}
    </section>
  )
}
