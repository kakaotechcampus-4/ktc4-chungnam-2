import { useId, type ReactNode } from 'react'

/**
 * 늘 하나가 골라져 있는 2~4개 중 하나 고르기(#1539). ink-100 홈 안에서 고른 칸만 흰 면 + brand 글자로 떠오른다.
 * 속은 브라우저 라디오라 화살표로 옮기고 화면 읽기는 「라디오 단추 1/3」으로 읽는다. 칸 높이 44px.
 * 아무것도 안 골랐을 수 있거나 칸이 많으면 `chip`을 쓴다.
 */
export default function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onChange,
  className = '',
}: {
  label: string
  options: readonly { key: T; label: ReactNode }[]
  value: T
  onChange: (key: T) => void
  className?: string
}) {
  const name = useId()
  return (
    <div role="radiogroup" aria-label={label} className={`flex gap-1 rounded-xl bg-ink-100 p-1 ${className}`}>
      {options.map((o) => (
        <label
          key={o.key}
          className="flex min-h-11 min-w-0 flex-1 cursor-pointer items-center justify-center rounded-lg px-2 text-center text-sm font-semibold text-ink-500 transition-colors hover:text-ink-700 has-[:checked]:bg-white has-[:checked]:font-bold has-[:checked]:text-brand-600 has-[:checked]:shadow-float has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-[var(--line-focus)]"
        >
          <input type="radio" name={name} checked={value === o.key} onChange={() => onChange(o.key)} className="sr-only" />
          {o.label}
        </label>
      ))}
    </div>
  )
}
