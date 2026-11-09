import { useId, type ReactNode } from 'react'

/** 0~100 정수. 분모가 0이면 0이다. */
export const percent = (value: number, max: number) => (max > 0 ? Math.min(100, Math.max(0, Math.round((value / max) * 100))) : 0)

/**
 * 비율을 글과 막대로 같이 보인다(#1539) — 위 줄은 뜻(「4명 중 3명이 의견을 남겼어요」)과 %, 아래는 brand-600 막대.
 * 숫자는 글에 꼭 남긴다(막대만으로는 3/4와 4/5가 갈리지 않는다). 막대는 화면 읽기에 progressbar 로 읽힌다.
 */
export default function ProgressBar({ label, value, max, className = '' }: { label: ReactNode; value: number; max: number; className?: string }) {
  const id = useId()
  const pct = percent(value, max)
  return (
    <div className={className}>
      <div className="mb-1 flex items-baseline justify-between gap-2 text-xs font-bold">
        <span id={id} className="text-ink-600">{label}</span>
        <span aria-hidden="true" className="shrink-0 text-brand-600">{pct}%</span>
      </div>
      <ProgressTrack value={value} max={max} labelledBy={id} />
    </div>
  )
}

/** 막대만 — 진행 막대 모양은 여기 한 곳이다. 할 일 카드(`TaskProgress`)도 이것을 쓴다. */
export function ProgressTrack({ value, max, labelledBy, valueText }: { value: number; max: number; labelledBy: string; valueText?: string }) {
  return (
    <div
      role="progressbar"
      aria-labelledby={labelledBy}
      aria-valuemin={0}
      aria-valuemax={max}
      aria-valuenow={value}
      aria-valuetext={valueText}
      className="h-1.5 overflow-hidden rounded-full bg-ink-100"
    >
      <div className="h-full rounded-full bg-[var(--action-fill)] transition-[width] duration-300 motion-reduce:transition-none" style={{ width: `${percent(value, max)}%` }} />
    </div>
  )
}
