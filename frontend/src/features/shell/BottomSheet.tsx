import { useRef, useState, type ReactNode } from 'react'

import { TAB_BAR_SPACE } from './layout'
import type { SheetStage } from './sheetStore'
import { useIsDesktop } from './useIsDesktop'

/**
 * 단계별 시트 윗변(Figma iPhone 16 852px 기준을 화면 비율로 옮김).
 * 1단계는 손잡이 + 제목 줄만 보인다(66px), 2단계는 지도가 같이 보이는 절반, 3단계는 거의 전체.
 */
const STAGE_TOP: Record<SheetStage, string> = {
  // 시트는 바닥까지 깔리고 탭 바가 그 위에 뜬다. 1단계는 손잡이와 제목 줄이 탭 바 위에 보이는 높이.
  1: `calc(100dvh - ${TAB_BAR_SPACE} - 66px)`,
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
 * 넓은 화면에서는 왼쪽 패널 안을 채우는 평범한 스크롤 영역이다 — 단계·손잡이·끌기·자동 확장이 없다(#338).
 * 지도 화면의 본문 영역(`main`)이라 스크린 리더의 「본문으로 이동」이 검색창·칩을 건너 여기로 온다(#1224).
 */
export default function BottomSheet({
  stage,
  onStageChange,
  header,
  top,
  banner,
  expandOnScroll = false,
  children,
}: {
  stage: SheetStage
  onStageChange: (stage: SheetStage) => void
  header: ReactNode
  top?: ReactNode
  /** 시트 윗변에 붙는 띠(연결 끊김 등). 손잡이 위에 온다. */
  banner?: ReactNode
  /** 2단계에서는 안을 스크롤하지 않고, 내용을 위로 끌면 3단계로 올린다(핀 상세 '3단계 자동 확장'). */
  expandOnScroll?: boolean
  children: ReactNode
}) {
  const desktop = useIsDesktop()
  const [dragY, setDragY] = useState<number | null>(null)
  const startY = useRef(0)
  const touchY = useRef<number | null>(null)

  if (desktop) {
    return (
      <main aria-label="탭 내용" className="relative flex min-h-0 flex-1 flex-col bg-[var(--surface-sheet)]">
        {top}
        {banner}
        {/* 위 여백은 패널 헤더의 pb-1(포커스 테두리 자리)과 합쳐 16px. */}
        <div className="shrink-0 px-4 pb-2 pt-3">{header}</div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 pb-6">{children}</div>
      </main>
    )
  }

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

  // 2단계 자동 확장 — 휠·터치로 내용을 위로 밀면 3단계로. 끌지 않으면 2단계에 머문다.
  const autoExpand = expandOnScroll && stage === 2
  const expandHandlers = autoExpand
    ? {
        onWheel: (e: React.WheelEvent) => e.deltaY > 0 && onStageChange(3),
        // 키보드로 안쪽에 들어가거나 입력칸을 누르면 스크롤할 수 있게 3단계로 올린다. 손가락·마우스로 버튼을 누를 때는 올리지 않는다 —
        // 누르는 순간(포커스) 시트가 움직여 손을 뗄 때 다른 자리에 떨어지면 그 누름이 버튼에 가지 않았다(e2e 「반대」, #1675).
        // 그 구분이 :focus-visible 이다(입력칸은 눌러도 참, 버튼은 키보드일 때만 참).
        onFocusCapture: (e: React.FocusEvent) => focusVisible(e.target) && onStageChange(3),
        // 누르면 아래에 내용이 펼쳐지는 자리(`data-sheet-expand`, 핀 상세 의견 고르기)는 누름이 끝난 뒤(click) 3단계로 편다.
        // 2단계는 안쪽 스크롤이 막혀 펼쳐진 사유 칸이 탭 막대 뒤에 가려졌다(#1694). 손을 뗀 뒤라 누름이 빗나가지 않는다.
        onClickCapture: (e: React.MouseEvent) => (e.target as Element).closest?.('[data-sheet-expand]') && onStageChange(3),
        onTouchStart: (e: React.TouchEvent) => (touchY.current = e.touches[0].clientY),
        onTouchMove: (e: React.TouchEvent) => {
          if (touchY.current !== null && touchY.current - e.touches[0].clientY > TAP_SLOP) {
            touchY.current = null
            onStageChange(3)
          }
        },
      }
    : {}

  return (
    <main
      aria-label="바텀시트"
      style={{
        top: dragging ? `calc(${STAGE_TOP[stage]} + ${dragY}px)` : STAGE_TOP[stage],
      }}
      className={`fixed inset-x-0 bottom-0 z-30 flex flex-col rounded-t-2xl bg-[var(--surface-sheet)] shadow-sheet ${
        dragging ? '' : 'transition-[top] duration-300 ease-out motion-reduce:transition-none'
      }`}
    >
      {top}
      {banner}
      <div
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={() => setDragY(null)}
        className="shrink-0 cursor-grab touch-none select-none px-4 pb-2"
      >
        {/* 끌기는 포인터로. 키보드는 Enter·Space 로 접고 펼치고, 위아래 화살표로 한 단계씩 옮긴다(3단계 포함). */}
        <div
          role="button"
          tabIndex={0}
          aria-label={`${stage === 1 ? '시트 펼치기' : '시트 접기'} · 위아래 화살표로 높이 조절`}
          onKeyDown={(e) => {
            const next =
              e.key === 'Enter' || e.key === ' ' ? (stage === 1 ? 2 : 1)
              : e.key === 'ArrowUp' && stage < 3 ? stage + 1
              : e.key === 'ArrowDown' && stage > 1 ? stage - 1
              : null
            if (next === null) return
            e.preventDefault()
            onStageChange(next as SheetStage)
          }}
          className="mx-auto mb-3 mt-2 h-1 w-12 rounded-full bg-ink-300"
        />
        {header}
      </div>
      <div
        hidden={stage === 1}
        {...expandHandlers}
        // 내용은 떠 있는 탭 바 밑으로 지나간다. 마지막 줄이 탭 바에 가리지 않게 그 높이 + 16 만큼 아래를 비운다.
        style={{ paddingBottom: `calc(${TAB_BAR_SPACE} + 16px)` }}
        className={`min-h-0 flex-1 overscroll-contain px-4 ${autoExpand ? 'overflow-hidden' : 'overflow-y-auto'}`}
      >
        {children}
      </div>
    </main>
  )
}

/** 키보드 포커스나 입력칸 포커스인지. :focus-visible 을 모르는 환경(테스트의 jsdom 일부)에서는 예전처럼 참으로 본다. */
function focusVisible(el: EventTarget): boolean {
  try {
    return el instanceof Element && el.matches(':focus-visible')
  } catch {
    return true
  }
}
