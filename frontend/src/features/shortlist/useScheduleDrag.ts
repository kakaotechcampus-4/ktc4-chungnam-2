import { useEffect, useRef, useState } from 'react'

import { dropSpot, UNSET_DAY, type DropSpot } from './schedule'
import { setDropHover } from './scheduleStore'

/** 이만큼 움직이기 전에는 끌기가 아니다(누르기). */
const START_PX = 6

/**
 * 끄는 동안 글자 선택을 막는다. 사파리는 ≡를 끄는 동안 지나간 글자를 다 선택하고,
 * 선택한 글을 통째로 끌어 버려 놓기가 끊겼다(2026-11-05 사파리 시연 영상).
 */
const blockSelect = (e: Event) => e.preventDefault()

/** 끄는 곳 — 확정 리스트 줄(`list`)이면 리스트 자리는 놓을 칸이 아니다. */
type From = 'list' | 'day'

/** 끄는 동안 `<html data-schedule-drag>`에 끄는 곳을 적는다. index.css가 놓을 칸에 점선을 긋고 나머지를 옅게 덮는다. */
const markDragging = (from: From | null) => {
  if (from) document.documentElement.dataset.scheduleDrag = from
  else delete document.documentElement.dataset.scheduleDrag
}

/**
 * 일정 칸으로 끌어 놓기 한 벌 — 「일정 짜기」 패널 카드, 「동선 보기」 그날 줄, 넓은 화면 확정 리스트 줄의 ≡가 같이 쓴다.
 * 포인터 이벤트라 마우스와 손가락을 같이 받는다(라이브러리 없이). 끄는 동안 놓을 자리를 스토어(`hover`)에 적어
 * 칸 테두리와 끼울 자리 선이 그려지고, 놓으면 `onDrop(자리)`를 부른다. 칸 밖에 놓으면 아무 일도 없다.
 */
export function useScheduleDrag(pinId: string, onDrop: (spot: DropSpot) => void) {
  const [drag, setDrag] = useState<{ x0: number; y0: number; x: number; y: number; from: From; active: boolean; spot: DropSpot | null } | null>(null)

  // 끄는 도중 줄이 사라지면(다른 구성원이 빼거나 확정을 해제, 다시 받기) 놓기가 오지 않는다 —
  // 선택 막기·덮개와 놓을 자리 표시를 남기지 않는다.
  const dragging = useRef(false)
  const release = () => {
    document.removeEventListener('selectstart', blockSelect)
    markDragging(null)
  }
  const end = () => {
    dragging.current = false
    release()
    setDrag(null)
    setDropHover(null)
  }
  useEffect(() => () => {
    release()
    if (dragging.current) setDropHover(null)
  }, [])

  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
      window.getSelection()?.removeAllRanges()
      document.addEventListener('selectstart', blockSelect)
      e.currentTarget.setPointerCapture?.(e.pointerId)
      dragging.current = true
      const from: From = e.currentTarget.closest<HTMLElement>('[data-day]')?.dataset.day === UNSET_DAY ? 'list' : 'day'
      setDrag({ x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, from, active: false, spot: null })
    },
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
      if (!drag) return
      const active = drag.active || Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) >= START_PX
      const spot = active ? dropSpot(e.clientX, e.clientY, pinId) : null
      if (active) markDragging(drag.from)
      setDrag({ ...drag, x: e.clientX, y: e.clientY, active, spot })
      setDropHover(spot && { ...spot, pinId })
    },
    onPointerUp: () => {
      if (drag?.active && drag.spot) onDrop(drag.spot)
      end()
    },
    onPointerCancel: end,
    onLostPointerCapture: end,
  }

  return { handlers, dragging: Boolean(drag?.active), ghost: drag?.active ? { x: drag.x, y: drag.y } : null }
}
