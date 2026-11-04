import { useEffect, useRef, useState } from 'react'

import { dropSpot, type DropSpot } from './schedule'
import { setDropHover } from './scheduleStore'

/** 이만큼 움직이기 전에는 끌기가 아니다(누르기). */
const START_PX = 6

/**
 * 일정 칸으로 끌어 놓기 한 벌 — 「일정 짜기」 패널 카드, 「동선 보기」 그날 줄, 넓은 화면 확정 리스트 줄의 ≡가 같이 쓴다.
 * 포인터 이벤트라 마우스와 손가락을 같이 받는다(라이브러리 없이). 끄는 동안 놓을 자리를 스토어(`hover`)에 적어
 * 칸 테두리와 끼울 자리 선이 그려지고, 놓으면 `onDrop(자리)`를 부른다. 칸 밖에 놓으면 아무 일도 없다.
 */
export function useScheduleDrag(pinId: string, onDrop: (spot: DropSpot) => void) {
  const [drag, setDrag] = useState<{ x0: number; y0: number; x: number; y: number; active: boolean; spot: DropSpot | null } | null>(null)

  // 끄는 도중 줄이 사라지면(다른 구성원이 빼거나 확정을 해제) 놓기가 오지 않는다 — 놓을 자리 표시를 남기지 않는다.
  const dragging = useRef(false)
  const end = () => {
    dragging.current = false
    setDrag(null)
    setDropHover(null)
  }
  useEffect(() => () => {
    if (dragging.current) setDropHover(null)
  }, [])

  const handlers = {
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
      e.currentTarget.setPointerCapture?.(e.pointerId)
      dragging.current = true
      setDrag({ x0: e.clientX, y0: e.clientY, x: e.clientX, y: e.clientY, active: false, spot: null })
    },
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => {
      if (!drag) return
      const active = drag.active || Math.hypot(e.clientX - drag.x0, e.clientY - drag.y0) >= START_PX
      const spot = active ? dropSpot(e.clientX, e.clientY, pinId) : null
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
