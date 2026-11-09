import { useId, type ReactNode } from 'react'

/** 다 찼는지 — 막대와 % 글자가 초록이 된다. */
export const isFull = (value: number, max: number) => max > 0 && value >= max

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
        <span aria-hidden="true" className={`shrink-0 ${isFull(value, max) ? 'text-[var(--good-text)]' : 'text-link'}`}>{pct}%</span>
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
      {/* 채우는 동안은 할 일 파랑, 다 차면 좋음 초록(완료). 빨강·주황은 쓰지 않는다 — 진행이 적은 건 오류가 아니다(영역 분리 규칙). */}
      <div
        className={`h-full rounded-full transition-[width,background-color] duration-300 motion-reduce:transition-none ${isFull(value, max) ? 'bg-[var(--good-line)]' : 'bg-[var(--action-fill)]'}`}
        style={{ width: `${percent(value, max)}%` }}
      />
    </div>
  )
}
