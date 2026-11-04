import { createPortal } from 'react-dom'

/**
 * 일정 칸으로 끄는 동안 손가락을 따라오는 이름 카드 — 「일정 짜기」 패널 안의 카드와 왼쪽 확정 리스트 줄의 ≡가 같이 쓴다.
 * 패널(아래 시트)의 움직임에 끌려가지 않게 body 에 그린다. 누름은 통과시켜서(pointer-events-none) 그 밑의 칸이 잡힌다.
 */
export default function DragGhost({ name, x, y }: { name: string; x: number; y: number }) {
  return createPortal(
    <div
      aria-hidden="true"
      style={{ left: x, top: y }}
      className="pointer-events-none fixed z-[60] -translate-x-1/2 -translate-y-1/2 rounded-lg bg-white px-3 py-2 text-body font-semibold text-ink-900 shadow-float ring-1 ring-ink-200"
    >
      {name}
    </div>,
    document.body,
  )
}
