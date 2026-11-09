/**
 * 빈 지도를 길게 눌러 지도 자리 메뉴 열기(#1549). 터치·펜만 — 마우스는 우클릭(카카오 `rightclick`)이다.
 * 핀·말풍선 같은 버튼 위에서는 시작하지 않는다(핀 길게 누르기는 집기다, #1012). 손가락이 SLOP 넘게 움직이면(지도 끌기) 그만둔다.
 * 누르는 동안 손가락 둘레에 원이 차오르고(`press-ring`, 동작 줄이기면 그대로 서 있는 원), 다 차면 onPress 를 부른다.
 */
export const HOLD_MS = 500
const SLOP = 10

export type LongPress = {
  /** 지도 끌기가 시작되면 그만둔다. */
  cancel: () => void
  /** 방금 길게 누르기가 끝났다 — 뒤따라오는 지도 click 을 버린다(그대로 두면 막 연 메뉴를 닫는다). */
  justFired: () => boolean
  detach: () => void
}

export function attachLongPress(container: HTMLElement, onPress: (x: number, y: number) => void): LongPress {
  let timer: ReturnType<typeof setTimeout> | undefined
  let start: { x: number; y: number; id: number } | null = null
  let ring: HTMLElement | null = null
  let firedAt = 0

  const cancel = () => {
    clearTimeout(timer)
    start = null
    ring?.remove()
    ring = null
  }

  const onDown = (e: PointerEvent) => {
    // 두 번째 손가락(확대)도 지도 끌기라 그만둔다.
    if (e.pointerType === 'mouse' || !e.isPrimary || (e.target as Element | null)?.closest('button, a, input')) return cancel()
    const box = container.getBoundingClientRect()
    const x = e.clientX - box.left
    const y = e.clientY - box.top
    start = { x: e.clientX, y: e.clientY, id: e.pointerId }
    ring = document.createElement('span')
    ring.className = 'press-ring'
    ring.setAttribute('aria-hidden', 'true')
    ring.style.cssText = `left:${x}px;top:${y}px;--hold:${HOLD_MS}ms`
    ring.innerHTML = '<svg viewBox="0 0 48 48" width="48" height="48"><circle cx="24" cy="24" r="21" pathLength="100" /></svg>'
    container.parentElement?.appendChild(ring)
    timer = setTimeout(() => {
      cancel()
      firedAt = Date.now()
      onPress(x, y)
    }, HOLD_MS)
  }
  const onMove = (e: PointerEvent) => {
    if (start && e.pointerId === start.id && Math.hypot(e.clientX - start.x, e.clientY - start.y) > SLOP) cancel()
  }
  const onEnd = (e: PointerEvent) => {
    if (start && e.pointerId === start.id) cancel()
  }

  // 카카오 지도가 안쪽에서 누름을 먼저 가져가도 보이게 잡는 단계(capture)에서 듣는다.
  const opts = { capture: true }
  container.addEventListener('pointerdown', onDown, opts)
  container.addEventListener('pointermove', onMove, opts)
  container.addEventListener('pointerup', onEnd, opts)
  container.addEventListener('pointercancel', onEnd, opts)
  return {
    cancel,
    justFired: () => Date.now() - firedAt < 700,
    detach: () => {
      cancel()
      container.removeEventListener('pointerdown', onDown, opts)
      container.removeEventListener('pointermove', onMove, opts)
      container.removeEventListener('pointerup', onEnd, opts)
      container.removeEventListener('pointercancel', onEnd, opts)
    },
  }
}
