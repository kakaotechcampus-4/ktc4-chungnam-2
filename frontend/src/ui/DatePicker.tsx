import { useEffect, useRef, useState } from 'react'
import { Popover } from 'radix-ui'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-react'

import { ClearButton } from './TextField'

const WEEK = ['일', '월', '화', '수', '목', '금', '토']
const DAY_MS = 86_400_000

/** 날짜는 'YYYY-MM-DD' 글자로 주고받는다(입력칸 값과 같다). 계산은 UTC 자정이라 시간대에 흔들리지 않는다. */
const ms = (iso: string) => Date.parse(`${iso}T00:00:00Z`)
const iso = (t: number) => new Date(t).toISOString().slice(0, 10)
const addDays = (day: string, n: number) => iso(ms(day) + n * DAY_MS)
const weekday = (day: string) => new Date(ms(day)).getUTCDay()
const parts = (day: string) => day.split('-').map(Number) as [number, number, number]
/** 그 달로 옮기되 날은 그 달 끝을 넘지 않는다(1월 31일 → 2월 28일). */
function addMonths(day: string, n: number) {
  const [y, m, d] = parts(day)
  const last = new Date(Date.UTC(y, m - 1 + n + 1, 0)).getUTCDate()
  return iso(Date.UTC(y, m - 1 + n, Math.min(d, last)))
}
function today() {
  const t = new Date()
  return iso(Date.UTC(t.getFullYear(), t.getMonth(), t.getDate()))
}
const clamp = (day: string, min?: string, max?: string) => (min && day < min ? min : max && day > max ? max : day)

/** 칸에 보이는 글자: 2026.11.8 (일) */
function shown(day: string) {
  const [y, m, d] = parts(day)
  return `${y}.${m}.${d} (${WEEK[weekday(day)]})`
}

/**
 * 날짜 입력칸(`field` 틀) + 누르면 아래에 붙는 달력. 브라우저 날짜 칸의 달력은 색·글자를 못 바꿔서 대신 쓴다.
 * 바깥 `<label>`로 감싸면 그 글자가 칸 이름이 된다. `min`·`max` 밖의 날은 누를 수 없다.
 * 달력은 화살표(하루·한 주), PageUp/PageDown(한 달)으로 옮기고 Enter로 고른다. Esc는 닫기.
 */
export default function DatePicker({
  value,
  onChange,
  min,
  max,
  clearLabel,
  placeholder = '날짜 선택',
  ...aria
}: {
  value: string
  onChange: (day: string) => void
  min?: string
  max?: string
  /** 주면 값이 있을 때 ✕가 생긴다(비워도 되는 칸). */
  clearLabel?: string
  placeholder?: string
  'aria-invalid'?: boolean
  'aria-describedby'?: string
}) {
  const [open, setOpen] = useState(false)
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Anchor className="field w-full">
        <Popover.Trigger {...aria} className="min-h-11 min-w-0 flex-1 text-left outline-none">
          {value ? shown(value) : <span className="text-ink-500">{placeholder}</span>}
        </Popover.Trigger>
        {value && clearLabel ? (
          <ClearButton label={clearLabel} onClick={() => onChange('')} />
        ) : (
          <CalendarDays size={16} className="shrink-0 text-ink-500" aria-hidden="true" />
        )}
      </Popover.Anchor>
      <Popover.Portal>
        <Popover.Content
          aria-label="날짜 고르기"
          align="start"
          sideOffset={8}
          collisionPadding={16}
          onOpenAutoFocus={(e) => e.preventDefault()}
          className="z-50 rounded-2xl border border-ink-200 bg-white p-4 shadow-float outline-none"
        >
          <Calendar
            autoFocus
            value={value}
            min={min}
            max={max}
            onPick={(day) => {
              onChange(day)
              setOpen(false)
            }}
          />
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}

/** 요일별 글자·면 — 일요일 빨강, 토요일 파랑(colors.md 6절의 달력 예외). */
const DAY_TONE: Record<number, { head: string; day: string }> = {
  0: { head: 'text-[var(--day-sun-text)]', day: 'bg-[var(--day-sun-bg)] text-[var(--day-sun-text)]' },
  6: { head: 'text-[var(--day-sat-text)]', day: 'bg-[var(--day-sat-bg)] text-[var(--day-sat-text)]' },
}

/**
 * 한 달 달력. 칸에 붙는 `DatePicker`도, 화면에 바로 까는 곳(확정 탭 「넣을 날짜」)도 이것을 쓴다.
 * `min`·`max` 밖의 날은 회색 원으로 어둡게 두고 누를 수 없다. 달 넘기기도 그 범위 안에서만 된다.
 * `autoFocus`면 처음에 커서 날로 초점을 옮긴다(달력 창을 열 때). 화면에 까는 곳은 끈다 — 탭을 열 때 초점을 뺏지 않는다.
 */
export function Calendar({
  value,
  min,
  max,
  onPick,
  autoFocus = false,
  dayName,
  marked,
  className = 'w-[19.25rem]',
}: {
  value: string
  min?: string
  max?: string
  onPick: (day: string) => void
  autoFocus?: boolean
  /** 날 이름 뒤에 붙일 말(확정 탭의 「둘째 날」). */
  dayName?: (day: string) => string | undefined
  /** 숫자 아래 점을 찍을 날(동선 보기의 장소를 넣은 날). 점은 보이기만 하고 뜻은 `dayName`으로 읽힌다. */
  marked?: (day: string) => boolean
  className?: string
}) {
  const now = today()
  // 커서는 키보드로 옮기는 날이고, 커서가 있는 달을 그린다. 처음에는 고른 날(없으면 오늘)에 둔다.
  const [cursor, setCursor] = useState(() => clamp(value || now, min, max))
  const grid = useRef<HTMLDivElement>(null)
  // 열 때와 키보드로 옮길 때만 그 날로 초점을 옮긴다 — 「다음 달」을 누른 초점은 그 버튼에 둔다.
  const follow = useRef(autoFocus)
  useEffect(() => {
    if (follow.current) grid.current?.querySelector<HTMLButtonElement>(`[data-day="${cursor}"]`)?.focus()
    follow.current = false
  }, [cursor])

  const [y, m] = parts(cursor)
  const first = `${y}-${String(m).padStart(2, '0')}-01`
  const length = new Date(Date.UTC(y, m, 0)).getUTCDate()
  const days = Array.from({ length }, (_, i) => addDays(first, i))
  const out = (day: string) => Boolean((min && day < min) || (max && day > max))
  // 달 넘기기 버튼은 그 달 전체가 범위 밖이면 끈다.
  const prevOff = Boolean(min && addDays(first, -1) < min)
  const nextOff = Boolean(max && addDays(first, length) > max)

  const move = (next: string) => setCursor(clamp(next, min, max))
  function onKey(e: React.KeyboardEvent) {
    const step: Record<string, () => string> = {
      ArrowLeft: () => addDays(cursor, -1),
      ArrowRight: () => addDays(cursor, 1),
      ArrowUp: () => addDays(cursor, -7),
      ArrowDown: () => addDays(cursor, 7),
      PageUp: () => addMonths(cursor, -1),
      PageDown: () => addMonths(cursor, 1),
    }
    if (!step[e.key]) return
    e.preventDefault()
    follow.current = true
    move(step[e.key]())
  }

  return (
    <div className={className}>
      <div className="mb-2 flex items-center justify-between">
        <button type="button" aria-label="이전 달" disabled={prevOff} onClick={() => move(addMonths(cursor, -1))} className="btn-text flex size-11 items-center justify-center">
          <ChevronLeft size={20} aria-hidden="true" />
        </button>
        <p aria-live="polite" className="text-base font-bold text-ink-900">
          {y}년 {m}월
        </p>
        <button type="button" aria-label="다음 달" disabled={nextOff} onClick={() => move(addMonths(cursor, 1))} className="btn-text flex size-11 items-center justify-center">
          <ChevronRight size={20} aria-hidden="true" />
        </button>
      </div>
      <div className="grid grid-cols-7 text-center text-xs font-semibold text-ink-500" aria-hidden="true">
        {WEEK.map((w, i) => (
          <span key={w} className={`py-1.5 ${DAY_TONE[i]?.head ?? ''}`}>{w}</span>
        ))}
      </div>
      <div ref={grid} onKeyDown={onKey} className="grid grid-cols-7 gap-y-1">
        {/* 1일 앞의 빈칸 — 다른 달 날짜는 그리지 않는다. */}
        {weekday(first) > 0 && <span style={{ gridColumn: `span ${weekday(first)}` }} />}
        {days.map((day) => {
          const picked = day === value
          const off = out(day)
          const d = parts(day)[2]
          const tone = DAY_TONE[weekday(day)]?.day
          return (
            <button
              key={day}
              type="button"
              data-day={day}
              tabIndex={day === cursor ? 0 : -1}
              disabled={off}
              aria-pressed={picked}
              aria-current={day === now ? 'date' : undefined}
              aria-label={[`${y}년 ${m}월 ${d}일 ${WEEK[weekday(day)]}요일`, dayName?.(day)].filter(Boolean).join(' ')}
              onClick={() => onPick(day)}
              className={[
                'relative mx-auto flex size-11 items-center justify-center rounded-full text-base transition-colors',
                'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--line-focus)]',
                // 오늘은 테두리 한 줄 — 주말 면·고른 날 채움 어디에 와도 보인다.
                day === now ? 'font-bold ring-1 ring-inset ring-[var(--action-fill)]' : '',
                off
                  ? 'cursor-default bg-ink-50 text-ink-400'
                  : picked
                    ? 'bg-[var(--action-fill)] font-bold text-white'
                    : `press font-semibold ${tone ?? 'text-ink-900'}`,
              ].join(' ')}
            >
              {d}
              {marked?.(day) && (
                <span aria-hidden="true" className={`absolute bottom-1.5 size-1 rounded-full ${picked ? 'bg-white' : 'bg-[var(--action-fill)]'}`} />
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
