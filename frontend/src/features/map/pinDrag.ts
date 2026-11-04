import { create } from 'zustand'

import type { Pin } from './model'

/**
 * 핀을 끌어 휴지통에 버리기(#1012). 지도 핀(카카오 오버레이, React 밖)과 목록 카드가 같은 함수를 붙인다.
 * - 마우스: 누른 채 SLOP 넘게 움직이면 집는다.
 * - 터치: 움직이지 않고 HOLD_MS 동안 누르면 집는다. 그 전에 움직이면 지도 끌기·목록 스크롤이라 놓아준다.
 *   짧게 누르면 지금처럼 상세가 열린다(클릭은 그대로 간다). 빈 지도 누르기(핀 찍기 말풍선, #486)는 핀 위가 아니라 겹치지 않는다.
 * 집으면 핀 그림(ghost)이 손을 따라오고, 휴지통(TrashDropZone)이 나타난다. 휴지통 위에서 놓으면 바로 지운다.
 * 집은 뒤 놓으면 끌었든 안 끌었든 클릭을 막는다 — 놓을 때 상세가 열리지 않게.
 */
const HOLD_MS = 400
const SLOP = 8
/** 휴지통 둘레로 이만큼(px)은 위에 온 것으로 본다 — 손가락이 가리는 몫. */
const BIN_MARGIN = 16

export type PinDrag = {
  pin: Pin
  /** 손을 따라오는 핀 그림(svg 마크업, 핀 이름은 들어 있지 않다). */
  ghost: string
  x: number
  y: number
  touch: boolean
  over: boolean
  /** 'drag' 끄는 중 · 'drop' 휴지통 위에서 놓음(들어가는 움직임이 끝나면 비운다). */
  phase: 'drag' | 'drop'
  /** 놓은 핀을 감춰 둔 것을 되돌린다 — 지우지 못했을 때 부른다. */
  release: () => void
}

type DragState = { drag: PinDrag | null; set: (drag: PinDrag | null) => void }

export const usePinDragStore = create<DragState>((set) => ({ drag: null, set: (drag) => set({ drag }) }))

/** 휴지통 자리. 같은 때 하나만 그려진다(모바일은 탭 시트, 넓은 화면은 지도 영역). */
const BIN_SELECTOR = '[data-trash-bin]'

function overBin(x: number, y: number): boolean {
  const r = document.querySelector(BIN_SELECTOR)?.getBoundingClientRect()
  if (!r) return false
  return x >= r.left - BIN_MARGIN && x <= r.right + BIN_MARGIN && y >= r.top - BIN_MARGIN && y <= r.bottom + BIN_MARGIN
}

/** 휴지통 가운데 — 놓은 핀이 이리로 들어간다. */
export function binCenter(): { x: number; y: number } | null {
  const r = document.querySelector(BIN_SELECTOR)?.getBoundingClientRect()
  return r ? { x: r.left + r.width / 2, y: r.top + r.height / 2 } : null
}

/**
 * el 을 끌 수 있게 한다. 떼는 함수를 돌려준다. `can_delete` 가 false 인 핀에는 붙이지 않는다(부르는 쪽이 거른다) —
 * 그래야 길게 눌러도 떨림 없이 상세만 열린다.
 */
export function attachTrashDrag(el: HTMLElement, getPin: () => Pin, ghost: () => string): () => void {
  const store = usePinDragStore.getState
  let start: { x: number; y: number; id: number; touch: boolean } | null = null
  let timer: ReturnType<typeof setTimeout> | undefined
  let picked = false
  let swallowClick = false

  const reset = () => {
    clearTimeout(timer)
    start = null
    if (picked) el.style.opacity = ''
    picked = false
  }

  const pick = (x: number, y: number) => {
    if (!start) return
    picked = true
    el.style.opacity = '0.3'
    store().set({ pin: getPin(), ghost: ghost(), x, y, touch: start.touch, over: overBin(x, y), phase: 'drag', release: () => (el.style.opacity = '') })
  }

  const onDown = (e: PointerEvent) => {
    if (e.button !== 0 || store().drag) return
    const touch = e.pointerType !== 'mouse'
    start = { x: e.clientX, y: e.clientY, id: e.pointerId, touch }
    // 지도 위로 나가도 움직임을 계속 받는다.
    el.setPointerCapture?.(e.pointerId)
    if (touch) timer = setTimeout(() => start && pick(start.x, start.y), HOLD_MS)
  }

  const onMove = (e: PointerEvent) => {
    if (!start || e.pointerId !== start.id) return
    if (!picked) {
      if (Math.hypot(e.clientX - start.x, e.clientY - start.y) <= SLOP) return
      if (start.touch) return reset() // 길게 누르기 전에 움직였다 — 지도 끌기·스크롤이다.
      pick(e.clientX, e.clientY)
    }
    // 시트 끌기·지도 끌기가 같은 움직임을 받지 않게 한다.
    e.stopPropagation()
    const drag = store().drag
    if (drag?.phase === 'drag') store().set({ ...drag, x: e.clientX, y: e.clientY, over: overBin(e.clientX, e.clientY) })
  }

  const onUp = (e: PointerEvent) => {
    if (!start || e.pointerId !== start.id) return
    if (picked) {
      swallowClick = true
      const drag = store().drag
      const over = drag?.phase === 'drag' && overBin(e.clientX, e.clientY)
      el.style.opacity = over ? '0' : ''
      picked = false
      if (drag) store().set(over ? { ...drag, over: true, phase: 'drop' } : null)
    }
    reset()
  }

  const onCancel = () => {
    if (picked) store().set(null)
    reset()
  }

  const onClick = (e: MouseEvent) => {
    if (!swallowClick) return
    swallowClick = false
    e.preventDefault()
    e.stopImmediatePropagation()
  }

  // 집은 뒤에는 화면이 스크롤되지 않게 한다(passive 가 아니어야 막힌다).
  const onTouchMove = (e: TouchEvent) => {
    if (!picked) return
    e.preventDefault()
    e.stopPropagation()
  }
  // 길게 누르면 뜨는 기기 메뉴(Android 문맥 메뉴, iOS 미리보기)를 막는다.
  const onContextMenu = (e: Event) => e.preventDefault()

  el.style.setProperty('-webkit-touch-callout', 'none')
  el.style.userSelect = 'none'
  el.addEventListener('pointerdown', onDown)
  el.addEventListener('pointermove', onMove)
  el.addEventListener('pointerup', onUp)
  el.addEventListener('pointercancel', onCancel)
  el.addEventListener('click', onClick, true)
  el.addEventListener('touchmove', onTouchMove, { passive: false })
  el.addEventListener('contextmenu', onContextMenu)
  return () => {
    onCancel()
    el.removeEventListener('pointerdown', onDown)
    el.removeEventListener('pointermove', onMove)
    el.removeEventListener('pointerup', onUp)
    el.removeEventListener('pointercancel', onCancel)
    el.removeEventListener('click', onClick, true)
    el.removeEventListener('touchmove', onTouchMove)
    el.removeEventListener('contextmenu', onContextMenu)
  }
}
