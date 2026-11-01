import { useEffect, useRef, useState } from 'react'
import { GripVertical, Trash2 } from 'lucide-react'

import type { ShortlistItemDto } from './model'

const SWIPE_W = 90
/** 줄 높이 + 간격(px). 끌어서 순서 바꿀 때 몇 칸 움직였는지 이 값으로 센다. */
const ROW_STEP = 68
/** 이만큼 움직이지 않고 떼면 끌기·밀기가 아니라 누르기다. */
const TAP_PX = 6

/**
 * 확정 리스트(Figma 7절). 줄을 왼쪽으로 밀면 빨강 「🗑 빼기」, ≡ 를 끌면 순서가 바뀐다.
 * 빼기는 핀 삭제가 아니라 확정 해제라서 '삭제'라고 부르지 않는다. 「확정 해제」 글자 버튼은 밀기의 대체 수단이다.
 * ≡ 를 끌지 않고 누르면 줄 아래에 「위로」「아래로」가 펼쳐진다 — 끌기가 안 되는 VoiceOver·손 대신 탭만으로 바꾼다(#959).
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
  const [moving, setMoving] = useState<string | null>(null)
  const startY = useRef(0)
  const dragged = useRef(false)
  const target = drag ? clamp(drag.index + Math.round(drag.dy / ROW_STEP), 0, items.length - 1) : null

  return (
    <ol className="space-y-2 pb-[100px]">
      {items.map((item, i) => (
        <SwipeRow
          key={item.id}
          item={item}
          n={i + 1}
          total={items.length}
          lifted={drag?.index === i ? drag.dy : null}
          moving={moving === item.id}
          onOpen={() => onOpen(item.pin.id)}
          onRemove={() => onRemove(item)}
          onMove={(to) => onReorder(i, to)}
          handle={
            <button
              type="button"
              aria-label={`${item.pin.place_name} 순서 바꾸기`}
              aria-expanded={moving === item.id}
              className="-my-2 -mr-2 flex size-11 shrink-0 cursor-grab touch-none items-center justify-center text-ink-400"
              onPointerDown={(e) => {
                startY.current = e.clientY
                dragged.current = false
                setDrag({ index: i, dy: 0 })
                e.currentTarget.setPointerCapture(e.pointerId)
              }}
              onPointerMove={(e) => {
                if (drag?.index !== i) return
                const dy = e.clientY - startY.current
                if (Math.abs(dy) >= TAP_PX) dragged.current = true
                setDrag({ index: i, dy })
              }}
              onPointerUp={() => {
                if (target !== null && target !== i) onReorder(i, target)
                setDrag(null)
              }}
              onPointerCancel={() => setDrag(null)}
              // 끌고 놓은 뒤 따라오는 click 은 누르기가 아니다.
              onClick={() => {
                if (dragged.current) return void (dragged.current = false)
                setMoving((id) => (id === item.id ? null : item.id))
              }}
              onKeyDown={(e) => {
                if (e.key === 'ArrowUp' && i > 0) onReorder(i, i - 1)
                if (e.key === 'ArrowDown' && i < items.length - 1) onReorder(i, i + 1)
              }}
            >
              <GripVertical size={20} aria-hidden="true" />
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
  total,
  lifted,
  moving,
  onOpen,
  onRemove,
  onMove,
  handle,
}: {
  item: ShortlistItemDto
  n: number
  total: number
  lifted: number | null
  moving: boolean
  onOpen: () => void
  onRemove: () => void
  /** 0부터 센 새 자리. */
  onMove: (to: number) => void
  handle: React.ReactNode
}) {
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState(false)
  const swipe = useRef<{ x: number; base: number } | null>(null)
  const [swiping, setSwiping] = useState(false)
  const x = swiping ? offset : open ? -SWIPE_W : 0
  // 밀기를 마친 손 뗌 뒤에 따라오는 click 은 열기가 아니다.
  const skipClick = useRef(false)
  const upRef = useRef<HTMLButtonElement>(null)
  const downRef = useRef<HTMLButtonElement>(null)
  // 줄이 옮겨지면 React 가 DOM 을 옮기며 누른 버튼의 포커스가 풀린다 — 옮긴 뒤 같은 버튼(끝이면 반대쪽)으로 돌려준다.
  const pressed = useRef<'up' | 'down' | null>(null)
  useEffect(() => {
    const was = pressed.current
    pressed.current = null
    if (was === 'up') (n > 1 ? upRef : downRef).current?.focus()
    if (was === 'down') (n < total ? downRef : upRef).current?.focus()
  }, [n, total])

  return (
    <li
      className="relative overflow-hidden rounded-xl"
      style={lifted !== null ? { transform: `translateY(${lifted}px)`, zIndex: 10, boxShadow: '0 4px 12px rgba(20,22,31,.18)' } : undefined}
    >
      {/* 닫혀 있을 땐 숨긴다 — 줄 뒤에 깔린 진회색이 둥근 모서리 틈으로 비쳐 테두리가 지저분해 보인다. */}
      <button
        type="button"
        onClick={onRemove}
        tabIndex={open ? 0 : -1}
        style={{ width: SWIPE_W }}
        // 숨길 때는 줄이 제자리로 미끄러져 돌아온 뒤(200ms)에 숨는다. 보일 때는 바로 보인다.
        className={`absolute inset-y-0 right-0 flex flex-col items-center justify-center gap-0.5 bg-ink-600 text-xs font-bold text-white transition-[visibility] duration-200 ${
          x === 0 && !swiping ? 'invisible' : ''
        }`}
      >
        <Trash2 size={20} aria-hidden="true" /> 빼기
      </button>
      {/* 줄 자체도 둥글게 — 네모 테두리를 둥근 li 가 잘라 모서리 테두리가 끊겨 보였다. */}
      <div
        style={{ transform: `translateX(${x}px)` }}
        className={`relative rounded-xl border border-ink-200 bg-white p-3 ${swiping ? '' : 'transition-transform duration-200'}`}
        onPointerDown={(e) => {
          skipClick.current = false
          // 핀 이름(열기 버튼) 위에서도 밀기는 시작한다. 그 밖의 버튼(≡·확정 해제·위로·아래로)은 제 일을 한다.
          if ((e.target as HTMLElement).closest('button:not([data-row-open])')) return
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
          // 밀지 않고 누른 건 열기(열기 버튼의 click 이 한다). 빼기가 열려 있으면 열지 않고 먼저 닫는다.
          if (moved < TAP_PX && !open) return
          skipClick.current = true
          if (moved < TAP_PX) return setOpen(false)
          setOpen(offset < -SWIPE_W / 2)
        }}
        onPointerCancel={() => {
          swipe.current = null
          setSwiping(false)
        }}
      >
        <div className="flex items-center gap-3">
          {/* 확정 리스트·동선 순서 번호는 골드 바탕 + 갈색 숫자(colors.md 3절). */}
          <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-[var(--pin-confirmed)] text-xs font-bold text-[var(--pin-confirmed-mark)]">
            {n}
          </span>
          {/* 키보드·VoiceOver로도 열리게 버튼이다(검색 결과 줄과 같다, #959). 키보드 click 은 detail 0 이라 밀기와 상관없다. */}
          <button
            type="button"
            data-row-open
            onClick={(e) => {
              if (e.detail !== 0 && skipClick.current) return
              onOpen()
            }}
            className="min-w-0 flex-1 select-none text-left"
          >
            <p className="truncate font-bold text-ink-900">{item.pin.place_name}</p>
            <p className="truncate text-xs text-ink-500">
              {item.pin.category}
              {item.pin.created_by_display_name && ` · ${item.pin.created_by_display_name}님이 찍은 핀`}
            </p>
          </button>
          {item.permissions.can_remove_from_shortlist && (
            <button type="button" onClick={onRemove} className="btn-text shrink-0 text-xs">
              확정 해제
            </button>
          )}
          {handle}
        </div>
        {moving && (
          <div className="mt-2 flex justify-end gap-2">
            <button
              ref={upRef}
              type="button"
              disabled={n === 1}
              onClick={() => {
                pressed.current = 'up'
                onMove(n - 2)
              }}
              className="btn-outline btn-sm"
            >
              위로
            </button>
            <button
              ref={downRef}
              type="button"
              disabled={n === total}
              onClick={() => {
                pressed.current = 'down'
                onMove(n)
              }}
              className="btn-outline btn-sm"
            >
              아래로
            </button>
          </div>
        )}
      </div>
    </li>
  )
}
