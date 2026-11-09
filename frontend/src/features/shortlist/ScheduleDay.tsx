import { Fragment, useEffect, useRef, type ReactNode } from 'react'
import { GripVertical } from 'lucide-react'

import DragGhost from './DragGhost'
import type { DropSpot } from './schedule'
import { useDropHover, useFlash } from './scheduleStore'
import { useScheduleDrag } from './useScheduleDrag'

/**
 * 일정 하루 칸 — 「일정 짜기」 패널(넓은 화면)과 「동선 보기」가 같이 쓴다. 칸이 끌어 놓을 자리다(`data-day`).
 * 끄는 줄이 위에 오면 점선 테두리가 된다(`drop-target`, index.css).
 * `color`(날짜 색 토큰, `dayLine`)를 주면 칸 왼쪽 4px 띠와 번호 원이 그 색이다 — 흰 카드가 여럿 늘어서면 날이 갈리지 않았다.
 * 빈 날은 점선 테두리의 낮은 한 줄로 줄여 장소가 있는 날이 먼저 보이게 한다.
 */
export function ScheduleDayBox({ day, title, count, color, children }: { day: string; title: string; count: number; color?: string; children: ReactNode }) {
  const hover = useDropHover()
  const empty = count === 0
  return (
    <section
      data-day={day}
      aria-label={title}
      data-over={hover?.day === day}
      style={color && !empty ? { borderLeft: `4px solid var(${color})` } : undefined}
      className={`drop-target rounded-xl border bg-surface ${empty ? 'flex items-center justify-between gap-2 border-dashed border-ink-300 px-3 py-2.5' : 'border-ink-200 p-3'}`}
    >
      <h3 className="text-sm font-bold text-ink-900">
        {title}
        {!empty && <span className="font-normal text-ink-500"> {count}곳</span>}
      </h3>
      <div className={empty ? 'shrink-0' : 'mt-2'}>{children}</div>
    </section>
  )
}

type ListProps = {
  day: string
  ids: string[]
  nameOf: (pinId: string) => string
  subOf?: (pinId: string) => string | undefined
  /** 있으면 이름이 상세를 여는 버튼이다(「동선 보기」). */
  onOpen?: (pinId: string) => void
  onTakeOut: (pinId: string) => void
  onDrop: (pinId: string, spot: DropSpot) => void
  onShift: (pinId: string, delta: -1 | 1) => void
  empty: string
  /** 번호 원 색(날짜 색 토큰). 없으면 회색 원. */
  color?: string
}

/** 그날 장소 줄 — 순서대로 번호를 달고, 끄는 동안 끼울 자리에 선을 긋는다. 번호 순서가 곧 「동선 보기」 순서다. */
export function ScheduleDayList({ day, ids, nameOf, subOf, onOpen, onTakeOut, onDrop, onShift, empty, color }: ListProps) {
  const hover = useDropHover()
  const at = hover?.day === day ? hover.index : null
  const marker = <li aria-hidden="true" className="h-0.5 rounded-full bg-[var(--action-fill)]" />
  if (ids.length === 0) return at === null ? <p className="text-xs text-ink-500">{empty}</p> : <ul>{marker}</ul>
  // 끼울 자리(at)는 끄는 줄을 뺀 순서라서, 끄는 줄을 뺀 목록에서 선이 들어갈 줄(그 앞)을 찾는다. 없으면 끝이다.
  const others = ids.filter((id) => id !== hover?.pinId)
  const markBefore = at !== null && at < others.length ? others[at] : null
  const markEnd = at !== null && at >= others.length
  return (
    <ol className="space-y-1.5">
      {ids.map((id, i) => {
        return (
          <Fragment key={id}>
            {id === markBefore && marker}
            <ScheduleRow
              pinId={id}
              n={i + 1}
              color={color}
              last={i === ids.length - 1}
              name={nameOf(id)}
              sub={subOf?.(id)}
              onOpen={onOpen}
              onTakeOut={onTakeOut}
              onDrop={onDrop}
              onShift={onShift}
            />
          </Fragment>
        )
      })}
      {markEnd && marker}
    </ol>
  )
}

/**
 * 일정 줄 — 번호 · 이름 · 「빼기」(확정 리스트로) · ≡. ≡ 를 끌어 다른 날·같은 날 다른 자리에 끼우고,
 * ≡ 에 포커스를 두고 ↑↓ 로도 한 칸씩 옮긴다(키보드). 옮기면 DOM 이 움직여 포커스가 풀려서 ≡ 로 돌려준다.
 */
function ScheduleRow({
  pinId,
  n,
  color,
  last,
  name,
  sub,
  onOpen,
  onTakeOut,
  onDrop,
  onShift,
}: {
  pinId: string
  n: number
  color?: string
  last: boolean
  name: string
  sub?: string
  onOpen?: (pinId: string) => void
  onTakeOut: (pinId: string) => void
  onDrop: (pinId: string, spot: DropSpot) => void
  onShift: (pinId: string, delta: -1 | 1) => void
}) {
  const { handlers, dragging, ghost } = useScheduleDrag(pinId, (spot) => onDrop(pinId, spot))
  const handle = useRef<HTMLButtonElement>(null)
  const keyMoved = useRef(false)
  const row = useRef<HTMLLIElement>(null)
  const flash = useFlash(pinId)
  // 확정 리스트에서 방금 넣은 줄 — 패널 안에서 보이게 옮기고 잠깐 테두리를 번지게 한다.
  useEffect(() => {
    if (flash) row.current?.scrollIntoView?.({ block: 'nearest', behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' })
  }, [flash])
  useEffect(() => {
    if (!keyMoved.current) return
    keyMoved.current = false
    handle.current?.focus()
  }, [n])

  const label = (
    <>
      <span className="block truncate text-body font-semibold text-ink-900">{name}</span>
      {sub && <span className="block truncate text-xs text-ink-500">{sub}</span>}
    </>
  )
  return (
    <li ref={row} data-pin={pinId} className={`flex items-center gap-2 rounded-xl bg-surface py-0.5 pl-2 pr-0.5 ring-1 ring-ink-200 ${dragging ? 'opacity-40' : ''} ${flash ? 'flash-ring' : ''}`}>
      {/* 번호 원은 AI 코스 날짜별 카드와 같다(ink-100 면, 날짜 색을 주면 그 색). 순서는 목록(ol)이 읽어 준다. */}
      <span
        aria-hidden="true"
        style={color ? { background: `var(${color})` } : undefined}
        className={`flex size-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${color ? 'text-white' : 'bg-ink-100 text-ink-700'}`}
      >
        {n}
      </span>
      {onOpen ? (
        <button type="button" onClick={() => onOpen(pinId)} className="press -mx-1 min-w-0 flex-1 rounded-md px-1 text-left">
          {label}
        </button>
      ) : (
        <span className="min-w-0 flex-1">{label}</span>
      )}
      <button
        type="button"
        aria-label={`${name} 일정에서 빼기`}
        onClick={(e) => {
          // 줄이 사라지면 포커스가 문서 처음으로 빠진다 — 다음 줄(없으면 앞 줄)의 ≡로 옮겨 둔다.
          const row = e.currentTarget.closest('li')
          const near = [row?.nextElementSibling, row?.previousElementSibling].find((el) => el?.matches('li[data-pin]'))
          near?.querySelector<HTMLElement>('button[aria-keyshortcuts]')?.focus()
          onTakeOut(pinId)
        }}
        className="btn-text shrink-0 text-xs"
      >
        빼기
      </button>
      <button
        ref={handle}
        type="button"
        aria-label={`${name} 순서 바꾸기`}
        aria-keyshortcuts="ArrowUp ArrowDown"
        className="flex size-11 shrink-0 cursor-grab touch-none items-center justify-center text-ink-400"
        {...handlers}
        onKeyDown={(e) => {
          if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return
          e.preventDefault()
          const up = e.key === 'ArrowUp'
          // 맨 위에서 ↑·맨 아래에서 ↓는 옮길 곳이 없다. 표시를 남기면 나중에 순서가 바뀔 때 이 줄이 포커스를 가져간다.
          if (up ? n === 1 : last) return
          keyMoved.current = true
          onShift(pinId, up ? -1 : 1)
        }}
      >
        <GripVertical size={20} aria-hidden="true" />
      </button>
      {ghost && <DragGhost name={name} x={ghost.x} y={ghost.y} />}
    </li>
  )
}
