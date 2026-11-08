import { useRef } from 'react'
import { Slider } from 'radix-ui'

/** 눈금(marks) 가운데 가장 가까운 것이 within 안이면 그 눈금, 아니면 값 그대로. */
export function snapToMark(value: number, marks: readonly number[], within: number): number {
  const near = marks.reduce<number | null>((a, b) => (a === null || Math.abs(b - value) < Math.abs(a - value) ? b : a), null)
  return near !== null && Math.abs(near - value) <= within ? near : value
}

/**
 * 값 하나를 끌어서 고르는 막대(#1416). 끌면 눈금 근처(snapWithin)에서 자석처럼 붙고, 붙는 순간 기기가 짧게 떤다(되는 기기만).
 * 키보드(←→ 한 칸, PageUp·PageDown 열 칸)로 옮길 때는 붙지 않는다 — 붙으면 눈금에서 한 칸씩 벗어날 수 없다.
 * 막대 높이 44가 누르는 곳이고, 손잡이는 24 원에 누르는 곳 44다. 화면 읽기는 `format`한 값(「3.5km」)을 읽는다.
 * onChange는 끄는 동안 계속, onCommit은 손을 떼거나 키를 누른 뒤 한 번이다.
 */
export default function RangeSlider({
  min,
  max,
  step,
  value,
  onChange,
  onCommit,
  marks = [],
  snapWithin = 0,
  format,
  markLabel = format,
  label,
}: {
  min: number
  max: number
  step: number
  value: number
  onChange: (value: number) => void
  onCommit?: (value: number) => void
  marks?: readonly number[]
  snapWithin?: number
  /** 화면 읽기가 읽는 값과 눈금 위의 값 글자. */
  format: (value: number) => string
  /** 눈금 아래 글자 — 기본값 눈금에 「기본」을 붙일 때처럼 따로 정한다. 없으면 format 이다. */
  markLabel?: (value: number) => string
  label: string
}) {
  const dragging = useRef(false)
  const at = (m: number) => `${((m - min) / (max - min)) * 100}%`
  return (
    <div>
      <Slider.Root
        min={min}
        max={max}
        step={step}
        value={[value]}
        onPointerDown={() => (dragging.current = true)}
        onKeyDown={() => (dragging.current = false)}
        onValueChange={([raw]) => {
          const next = dragging.current ? snapToMark(raw, marks, snapWithin) : raw
          if (next !== value && next !== raw) navigator.vibrate?.(8)
          onChange(next)
        }}
        // 끈 값은 그새 다시 그려져 붙은 값이고, 키보드는 같은 키 입력 안에서 오는 새 값이다 — 둘 다 받은 값을 그대로 넘긴다.
        onValueCommit={([v]) => onCommit?.(v)}
        className="relative flex h-11 w-full touch-none select-none items-center"
      >
        <Slider.Track className="relative h-1.5 grow rounded-full bg-ink-200">
          <Slider.Range className="absolute h-full rounded-full bg-brand-600" />
        </Slider.Track>
        <Slider.Thumb
          aria-label={label}
          aria-valuetext={format(value)}
          className="hit-44 block size-6 rounded-full border-2 border-brand-600 bg-white shadow-float outline-offset-2 focus-visible:outline-2 focus-visible:outline-[var(--line-focus)]"
        />
      </Slider.Root>
      {marks.length > 0 && (
        // 눈금 글자는 보이기만 한다 — 화면 읽기는 손잡이의 값과 범위를 읽는다.
        <div aria-hidden="true" className="relative h-4 text-label text-ink-500">
          {marks.map((m, i) => (
            <span
              key={m}
              // 손잡이가 이 눈금 위에 있으면 그 숫자를 굵은 파랑 + 밑줄로 짚는다(눈금 사이 값이면 아무것도 짚지 않는다).
              className={`absolute top-0 whitespace-nowrap ${i === 0 ? '' : i === marks.length - 1 ? '-translate-x-full' : '-translate-x-1/2'} ${
                m === value ? 'font-bold text-brand-700 underline underline-offset-4' : ''
              }`}
              style={{ left: at(m) }}
            >
              {markLabel(m)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}
