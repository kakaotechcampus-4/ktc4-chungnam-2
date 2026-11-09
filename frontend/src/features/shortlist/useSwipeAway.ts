import { useRef, useState, type MouseEvent, type PointerEvent } from 'react'

/** 이만큼 왼쪽으로 밀고 놓으면 뺀다(px). 덜 밀면 제자리로 돌아간다. */
export const SWIPE_AWAY_PX = 96
/** 이만큼 움직이기 전에는 밀기인지 스크롤인지 정하지 않는다. */
const DECIDE_PX = 10

/**
 * 줄을 왼쪽으로 밀어 빼기(#1669, 제스처 「밀어서 삭제」). 터치 화면(`pointer: fine`이 아님)에서만 켠다 — 마우스는 「빼기」 글자 버튼을 쓴다.
 * 가로로 먼저 움직일 때만 밀기다. 세로로 먼저 움직이면 시트 스크롤로 두고 손대지 않는다(줄은 `touch-action: pan-y`).
 * ≡ 손잡이(`aria-keyshortcuts`)에서 시작한 누름은 순서 바꾸기 끌기라 무시한다. 민 뒤의 클릭(이름 버튼)은 막는다.
 */
export function useSwipeAway(onAway: () => void) {
  const [enabled] = useState(() => !window.matchMedia?.('(pointer: fine)').matches)
  const [dx, setDx] = useState(0)
  const [dragging, setDragging] = useState(false)
  const start = useRef<{ x: number; y: number; id: number } | null>(null)
  const mode = useRef<'idle' | 'swipe' | 'scroll'>('idle')
  const swiped = useRef(false)

  if (!enabled) return { enabled, dx: 0, dragging: false, past: false, handlers: {} }

  const reset = () => {
    start.current = null
    mode.current = 'idle'
    setDragging(false)
  }

  const handlers = {
    onPointerDown(e: PointerEvent<HTMLElement>) {
      if ((e.target as HTMLElement).closest('[aria-keyshortcuts]')) return
      start.current = { x: e.clientX, y: e.clientY, id: e.pointerId }
      mode.current = 'idle'
      swiped.current = false
    },
    onPointerMove(e: PointerEvent<HTMLElement>) {
      const s = start.current
      if (!s || s.id !== e.pointerId || mode.current === 'scroll') return
      const mx = e.clientX - s.x
      const my = e.clientY - s.y
      if (mode.current === 'idle') {
        if (Math.abs(mx) < DECIDE_PX && Math.abs(my) < DECIDE_PX) return
        if (Math.abs(my) >= Math.abs(mx) || mx > 0) {
          mode.current = 'scroll'
          return
        }
        mode.current = 'swipe'
        swiped.current = true
        setDragging(true)
        e.currentTarget.setPointerCapture?.(e.pointerId)
      }
      setDx(Math.min(0, mx))
    },
    onPointerUp(e: PointerEvent<HTMLElement>) {
      if (mode.current === 'swipe') {
        e.currentTarget.releasePointerCapture?.(e.pointerId)
        if (dx <= -SWIPE_AWAY_PX) onAway()
        setDx(0)
      }
      reset()
    },
    onPointerCancel() {
      setDx(0)
      reset()
    },
    // 민 손을 뗄 때 이름 버튼이 눌린 것으로 치지 않는다.
    onClickCapture(e: MouseEvent<HTMLElement>) {
      if (!swiped.current) return
      swiped.current = false
      e.preventDefault()
      e.stopPropagation()
    },
  }
  return { enabled, dx, dragging, past: dx <= -SWIPE_AWAY_PX, handlers }
}
