import { useRef, useState, type ReactNode } from 'react'

import { TAB_BAR_H } from './layout'
import type { SheetStage } from './sheetStore'

/**
 * 단계별 시트 윗변(Figma iPhone 16 852px 기준을 화면 비율로 옮김).
 * 1단계는 손잡이 + 제목 줄만 보인다(66px), 2단계는 지도가 같이 보이는 절반, 3단계는 거의 전체.
 */
const STAGE_TOP: Record<SheetStage, string> = {
  1: `calc(100dvh - ${TAB_BAR_H + 66}px)`,
  2: '41dvh',
  3: '39px',
}

/** 이만큼 넘게 끌어야 단계가 바뀐다. 그 아래는 탭으로 본다. */
const DRAG_THRESHOLD = 40
const TAP_SLOP = 6

/**
 * 탭 3개가 함께 쓰는 바텀시트 하나(FE 회의 — 시트는 하나, 내용만 바뀐다).
 * 손잡이·제목 줄을 위로 끌면 한 단계 올라가고, 아래로 끌면 내려간다. 탭하면 접고 펼친다.
 * `top` 은 시트 위에 붙어 다니는 것(지도 버튼·토스트)을 넣는 자리다.
 */
export default function BottomSheet({
  stage,
  onStageChange,
  header,
  top,
  children,
}: {
  stage: SheetStage
  onStageChange: (stage: SheetStage) => void
  header: ReactNode
  top?: ReactNode
  children: ReactNode
}) {
  const [dragY, setDragY] = useState<number | null>(null)
  const startY = useRef(0)

  function onPointerDown(e: React.PointerEvent) {
    // 제목 줄 안의 버튼·드롭다운은 끌기가 아니라 그 버튼 동작이다.
    if ((e.target as HTMLElement).closest('button, a, input, select')) return
    startY.current = e.clientY
    setDragY(0)
    e.currentTarget.setPointerCapture(e.pointerId)
  }

  function onPointerMove(e: React.PointerEvent) {
    if (dragY === null) return
    setDragY(e.clientY - startY.current)
  }

  function onPointerUp() {
    if (dragY === null) return
    const dy = dragY
    setDragY(null)
    if (Math.abs(dy) < TAP_SLOP) {
      // 2단계 탭은 접기, 1·3단계 탭은 2단계로(Figma '손잡이 · 접기 영역').
      onStageChange(stage === 2 ? 1 : 2)
    } else if (dy < -DRAG_THRESHOLD && stage < 3) {
      onStageChange((stage + 1) as SheetStage)
    } else if (dy > DRAG_THRESHOLD && stage > 1) {
      onStageChange((stage - 1) as SheetStage)
    }
  }

  const dragging = dragY !== null && Math.abs(dragY) >= TAP_SLOP

  return (
    <section
      aria-label="바텀시트"
      style={{
        top: dragging ? `calc(${STAGE_TOP[stage]} + ${dragY}px)` : STAGE_TOP[stage],
        bottom: TAB_BAR_H,
      }}
      className={`fixed inset-x-0 z-30 flex flex-col rounded-t-2xl bg-white shadow-[0_-2px_12px_rgba(20,22,31,0.08)] ${
        dragging ? '' : 'transition-[top] duration-300 ease-out'
      }`}
    >
      {top}
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => setDragY(null)}
        className="shrink-0 cursor-grab touch-none select-none px-4 pb-2"
      >
        {/* 끌기는 포인터로, 키보드는 Enter·Space 로 접고 펼친다. */}
        <div
          role="button"
          tabIndex={0}
          aria-label={stage === 1 ? '시트 펼치기' : '시트 접기'}
          onKeyDown={(e) => {
            if (e.key !== 'Enter' && e.key !== ' ') return
            e.preventDefault()
            onStageChange(stage === 1 ? 2 : 1)
          }}
          className="mx-auto mb-3 mt-2 h-1 w-12 rounded-full bg-ink-300"
        />
        {header}
      </div>
      <div hidden={stage === 1} className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-6">
        {children}
      </div>
    </section>
  )
}
