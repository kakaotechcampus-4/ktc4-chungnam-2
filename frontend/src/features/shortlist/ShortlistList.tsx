import { useRef, useState } from 'react'
import { GripVertical, Trash2 } from 'lucide-react'

import type { ShortlistItemDto } from './model'

const SWIPE_W = 90
/** 줄 높이 + 간격(px). 끌어서 순서 바꿀 때 몇 칸 움직였는지 이 값으로 센다. */
const ROW_STEP = 68

/**
 * 확정 리스트(Figma 7절). 줄을 왼쪽으로 밀면 빨강 「🗑 빼기」, ≡ 를 끌면 순서가 바뀐다.
 * 빼기는 핀 삭제가 아니라 확정 해제라서 '삭제'라고 부르지 않는다. 「확정 해제」 글자 버튼은 밀기의 대체 수단이다.
 */
export default function ShortlistList({
  items,
  onOpen,
  onRemove,
  onReorder,
}: {
  items: ShortlistItemDto[]
  onOpen: (pinId: string) => void
  onRemove: (item: ShortlistItemDto) => void
  onReorder: (from: number, to: number) => void
}) {
  const [drag, setDrag] = useState<{ index: number; dy: number } | null>(null)
  const startY = useRef(0)
  const target = drag ? clamp(drag.index + Math.round(drag.dy / ROW_STEP), 0, items.length - 1) : null

  return (
    <ol className="space-y-2 pb-[100px]">
      {items.map((item, i) => (
        <SwipeRow
          key={item.id}
          item={item}
          n={i + 1}
          lifted={drag?.index === i ? drag.dy : null}
          onOpen={() => onOpen(item.pin.id)}
          onRemove={() => onRemove(item)}
          handle={
            <button
              type="button"
              aria-label={`${item.pin.place_name} 순서 바꾸기 (위·아래 화살표)`}
              className="cursor-grab touch-none p-1 text-ink-400"
              onPointerDown={(e) => {
                startY.current = e.clientY
                setDrag({ index: i, dy: 0 })
                e.currentTarget.setPointerCapture(e.pointerId)
              }}
              onPointerMove={(e) => drag?.index === i && setDrag({ index: i, dy: e.clientY - startY.current })}
              onPointerUp={() => {
                if (target !== null && target !== i) onReorder(i, target)
                setDrag(null)
              }}
              onPointerCancel={() => setDrag(null)}
              onKeyDown={(e) => {
                if (e.key === 'ArrowUp' && i > 0) onReorder(i, i - 1)
                if (e.key === 'ArrowDown' && i < items.length - 1) onReorder(i, i + 1)
              }}
            >
              <GripVertical size={18} />
            </button>
          }
        />
      ))}
    </ol>
  )
}

function clamp(n: number, lo: number, hi: number) {
  return Math.max(lo, Math.min(hi, n))
}

function SwipeRow({
  item,
  n,
  lifted,
  onOpen,
  onRemove,
  handle,
}: {
  item: ShortlistItemDto
  n: number
  lifted: number | null
  onOpen: () => void
  onRemove: () => void
  handle: React.ReactNode
}) {
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState(false)
  const swipe = useRef<{ x: number; base: number } | null>(null)
  const [swiping, setSwiping] = useState(false)
  const x = swiping ? offset : open ? -SWIPE_W : 0

  return (
    <li
      className="relative overflow-hidden rounded-xl"
      style={lifted !== null ? { transform: `translateY(${lifted}px)`, zIndex: 10, boxShadow: '0 4px 12px rgba(20,22,31,.18)' } : undefined}
    >
      <button
        type="button"
        onClick={onRemove}
        tabIndex={open ? 0 : -1}
        style={{ width: SWIPE_W }}
        className="absolute inset-y-0 right-0 flex flex-col items-center justify-center gap-0.5 bg-ink-600 text-xs font-bold text-white"
      >
        <Trash2 size={18} aria-hidden="true" /> 빼기
      </button>
      <div
        style={{ transform: `translateX(${x}px)` }}
        className={`relative flex items-center gap-3 border border-ink-200 bg-white p-3 ${swiping ? '' : 'transition-transform duration-200'}`}
        onPointerDown={(e) => {
          if ((e.target as HTMLElement).closest('button')) return
          swipe.current = { x: e.clientX, base: open ? -SWIPE_W : 0 }
          setOffset(swipe.current.base)
          setSwiping(true)
        }}
        onPointerMove={(e) => {
          if (!swipe.current) return
          setOffset(clamp(swipe.current.base + e.clientX - swipe.current.x, -SWIPE_W, 0))
        }}
        onPointerUp={(e) => {
          if (!swipe.current) return
          const moved = Math.abs(e.clientX - swipe.current.x)
          swipe.current = null
          setSwiping(false)
          if (moved < 6) {
            // 밀지 않고 누른 건 열기. 빼기가 열려 있으면 먼저 닫는다.
            if (open) setOpen(false)
            else onOpen()
            return
          }
          setOpen(offset < -SWIPE_W / 2)
        }}
        onPointerCancel={() => {
          swipe.current = null
          setSwiping(false)
        }}
      >
        {/* 확정 리스트·동선 순서 번호는 골드 바탕 + 갈색 숫자(colors.md 3절). */}
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--pin-confirmed)] text-xs font-bold text-[var(--pin-confirmed-mark)]">
          {n}
        </span>
        <div className="min-w-0 flex-1 select-none">
          <p className="truncate font-bold text-ink-900">{item.pin.place_name}</p>
          <p className="truncate text-xs text-ink-500">
            {item.pin.category}
            {item.pin.created_by_display_name && ` · ${item.pin.created_by_display_name}님이 찍은 핀`}
          </p>
        </div>
        {item.permissions.can_remove_from_shortlist && (
          <button type="button" onClick={onRemove} className="shrink-0 text-xs text-ink-500">
            확정 해제
          </button>
        )}
        {handle}
      </div>
    </li>
  )
}
