import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'

import SheetTitle from '@/ui/SheetTitle'

import { PANEL_GAP, PANEL_W, SIDE_PANEL_W } from './layout'
import { useSheetStore } from './sheetStore'
import { useIsPc } from './useIsDesktop'

/**
 * 넓은 화면에서 왼쪽 패널 옆에 붙는 패널(확정 탭 「일정 짜기」, 2026-11-03).
 * 왼쪽 패널 카드 오른쪽(접혀 있으면 화면 왼쪽 끝)에 같은 모양의 카드로 뜬다(#1538) — 왼쪽 목록과 같이 보면서 쓴다. 모달이 아니라서 딤이 없다.
 * 휴대폰에는 옆에 둘 자리가 없어서 쓰지 않는다.
 */
export default function SidePanel({ label, onClose, children }: { label: string; onClose: () => void; children: ReactNode }) {
  const panelOpen = useSheetStore((s) => s.panelOpen)
  const panelW = useIsPc() ? PANEL_W.pc : PANEL_W.tablet
  const ref = useRef<HTMLElement>(null)

  // 열면 패널로 포커스를 옮기고, 닫히면 연 버튼으로 돌려준다.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    ref.current?.focus({ preventScroll: true })
    return () => opener?.focus()
  }, [])

  return (
    <aside
      ref={ref}
      tabIndex={-1}
      aria-label={label}
      onKeyDown={(e) => e.key === 'Escape' && onClose()}
      style={{ left: panelOpen ? PANEL_GAP * 2 + panelW : PANEL_GAP, width: SIDE_PANEL_W }}
      className="enter-fade fixed inset-y-3 z-30 flex flex-col overflow-hidden rounded-2xl bg-surface shadow-float outline-none transition-[left] duration-300 ease-out motion-reduce:transition-none"
    >
      <header className="flex items-center gap-2 border-b border-ink-200 py-2 pl-4 pr-2">
        <div className="min-w-0 flex-1">
          <SheetTitle>{label}</SheetTitle>
        </div>
        <button type="button" onClick={onClose} aria-label={`${label} 닫기`} className="inline-flex size-11 items-center justify-center text-ink-600">
          <X size={20} aria-hidden="true" />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">{children}</div>
    </aside>
  )
}
