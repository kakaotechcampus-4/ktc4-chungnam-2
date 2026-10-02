import { useEffect, useRef, type ReactNode } from 'react'
import { Dialog } from 'radix-ui'

import Toaster from './Toaster'

/**
 * 화면 바닥에 붙는 모달 시트(Figma 프로필·계정 시트). 딤(--scrim)이 하단 바까지 덮고, 딤을 누르거나 Esc 로 닫는다.
 * 포커스 가두기는 Radix Dialog 가 맡는다(#299).
 * 토스트가 시트 윗변 위에 떠야 해서, 스크롤되는 시트 바깥 틀에 붙인다.
 */
export default function ModalSheet({
  label,
  onClose,
  children,
  overlay,
}: {
  label: string
  onClose: () => void
  children: ReactNode
  /** 시트 위에 다시 뜨는 확인 창 같은 것. */
  overlay?: ReactNode
}) {
  const sheetRef = useRef<HTMLElement>(null)

  // 부모가 이 컴포넌트를 통째로 빼서 닫으므로 Radix 의 닫힘 복귀가 돌지 않는다. 연 버튼으로 직접 돌려준다.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    return () => opener?.focus()
  }, [])

  return (
    <Dialog.Root open onOpenChange={(open) => !open && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-scrim" />
        {/* 내용 틀이 화면 전체라 빈 곳을 누르면 딤을 누른 것으로 본다. */}
        <Dialog.Content
          aria-describedby={undefined}
          aria-modal="true"
          onClick={onClose}
          // 첫 버튼이 아니라 시트 자체에 포커스를 둔다 — 열자마자 「로그아웃」에 포커스가 가면 안 된다.
          onOpenAutoFocus={(e) => {
            e.preventDefault()
            sheetRef.current?.focus()
          }}
          className="fixed inset-0 z-50 outline-none"
        >
          <Dialog.Title className="sr-only">{label}</Dialog.Title>
          <div className="absolute inset-x-0 bottom-0" onClick={(e) => e.stopPropagation()}>
            <Toaster controlsVisible={false} />
            {/* 홈 표시줄이 있으면 그만큼, 없으면 16px. */}
            <section ref={sheetRef} tabIndex={-1} className="max-h-[90dvh] overflow-y-auto rounded-t-2xl bg-white px-4 pb-[max(16px,env(safe-area-inset-bottom))] pt-2 outline-none">
              <div className="mx-auto mb-4 h-1 w-12 rounded-full bg-ink-300" aria-hidden="true" />
              {children}
            </section>
          </div>
          {overlay && <div onClick={(e) => e.stopPropagation()}>{overlay}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
