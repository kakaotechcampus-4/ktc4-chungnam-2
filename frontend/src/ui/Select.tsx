import { Select as S } from 'radix-ui'
import { Check, ChevronDown } from 'lucide-react'

/** Radix 는 빈 글자를 값으로 못 쓴다(「선택 없음」 자리라서). 「전체」 같은 빈 값은 이 글자로 바꿔 주고받는다. */
const EMPTY = '__empty__'
const toRadix = (v: string) => (v === '' ? EMPTY : v)
const fromRadix = (v: string) => (v === EMPTY ? '' : v)

/**
 * 고르는 목록(#1695). 누르면 칸 바로 아래에 흰 목록이 붙는다 — 브라우저 기본 목록은 글자·색·선택 표시를 못 바꿔서 대신 쓴다.
 * 칸은 「라벨 값 ▾」(높이 32, 누르는 곳 44)이고, 목록 줄은 높이 44에 고른 줄만 파란 글자 + ✓다.
 * 키보드는 위아래로 옮기고 Enter 로 고르며 Esc 로 닫는다(Radix Select).
 * 칸 폭은 가장 긴 선택지에 맞춰 고정한다 — 값을 바꿔도 옆 칸이 다음 줄로 밀리지 않는다. 줄 폭을 넘으면 「…」로 줄인다.
 */
export default function Select({
  label,
  ariaLabel = label,
  value,
  options,
  onChange,
}: {
  /** 칸 앞에 붙는 회색 글자. 정렬처럼 값만으로 읽히면 없다. */
  label?: string
  ariaLabel?: string
  value: string
  options: { value: string; label: string }[]
  onChange: (value: string) => void
}) {
  return (
    <S.Root value={toRadix(value)} onValueChange={(v) => onChange(fromRadix(v))}>
      <S.Trigger
        aria-label={ariaLabel}
        className="press hit-y-44 relative flex h-8 min-w-0 max-w-full items-center gap-1 whitespace-nowrap rounded-md border border-ink-200 bg-surface pl-2.5 pr-6 text-xs outline-none focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--line-focus)] data-[state=open]:border-brand-600"
      >
        {label && (
          <span aria-hidden="true" className="shrink-0 text-ink-500">
            {label}
          </span>
        )}
        <span className="grid min-w-0 grid-cols-[minmax(0,1fr)] font-semibold text-ink-900">
          {/* 폭 맞춤용 — 모든 선택지를 한 칸에 겹쳐 두고 보이지 않게 한다. */}
          {options.map((o) => (
            <span key={o.value} aria-hidden="true" className="invisible col-start-1 row-start-1 truncate">
              {o.label}
            </span>
          ))}
          <span className="col-start-1 row-start-1 truncate text-left">
            <S.Value />
          </span>
        </span>
        <S.Icon asChild>
          <ChevronDown size={12} className="absolute right-2 text-ink-500" aria-hidden="true" />
        </S.Icon>
      </S.Trigger>
      <S.Portal>
        <S.Content
          position="popper"
          sideOffset={6}
          collisionPadding={16}
          className="enter-fade z-50 max-h-[min(20rem,var(--radix-select-content-available-height))] min-w-[max(var(--radix-select-trigger-width),10rem)] overflow-hidden rounded-xl border border-ink-200 bg-surface shadow-float"
        >
          <S.Viewport className="p-1">
            {options.map((o) => (
              <S.Item
                key={o.value}
                value={toRadix(o.value)}
                className="flex min-h-11 cursor-pointer select-none items-center gap-2 rounded-lg px-3 text-sm text-ink-900 outline-none data-[highlighted]:bg-ink-50 data-[state=checked]:font-semibold data-[state=checked]:text-selected"
              >
                <S.ItemText>{o.label}</S.ItemText>
                <S.ItemIndicator className="ml-auto">
                  <Check size={16} aria-hidden="true" />
                </S.ItemIndicator>
              </S.Item>
            ))}
          </S.Viewport>
        </S.Content>
      </S.Portal>
    </S.Root>
  )
}
