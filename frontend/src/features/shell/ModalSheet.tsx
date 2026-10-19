import { useEffect, useRef, useState, type ReactNode } from 'react'
import { Dialog } from 'radix-ui'

import Toaster from './Toaster'

/** 손잡이를 이만큼(px) 넘게 끌어 내리면 닫는다. 덜 끌면 제자리로 돌아간다. */
const CLOSE_DRAG = 80

/**
 * 화면 바닥에 붙는 모달 시트(Figma 프로필·계정 시트). 딤(--scrim)이 하단 바까지 덮고, 딤을 누르거나 Esc 로 닫는다.
 * 포커스 가두기는 Radix Dialog 가 맡는다(#299).
 * 토스트가 시트 윗변 위에 떠야 해서, 스크롤되는 시트 바깥 틀에 붙인다.
 * 닫을 때는 시트가 내려가고(넓은 화면은 흐려지고) 효과가 끝난 뒤에 onClose 를 부른다.
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
  const [closing, setClosing] = useState(false)
  const [dragY, setDragY] = useState<number | null>(null)
  const startY = useRef(0)

  function requestClose() {
    // 동작 줄이기면 transition 이 없어 transitionend 가 오지 않는다 — 바로 닫는다.
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) onClose()
    else setClosing(true)
  }

  function onHandleUp() {
    if (dragY === null) return
    setDragY(null)
    if (dragY > CLOSE_DRAG) requestClose()
  }

  const sheetStyle = closing ? undefined : dragY ? { transform: `translateY(${Math.max(0, dragY)}px)` } : undefined

  // 부모가 이 컴포넌트를 통째로 빼서 닫으므로 Radix 의 닫힘 복귀가 돌지 않는다. 연 버튼으로 직접 돌려준다.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    return () => opener?.focus()
  }, [])

  return (
    <Dialog.Root open onOpenChange={(open) => !open && requestClose()}>
      <Dialog.Portal>
        <Dialog.Overlay
          className={`enter-fade fixed inset-0 z-50 bg-scrim transition-opacity duration-200 ease-out motion-reduce:transition-none ${closing ? 'opacity-0' : ''}`}
        />
        {/* 내용 틀이 화면 전체라 빈 곳을 누르면 딤을 누른 것으로 본다. */}
        <Dialog.Content
          aria-describedby={undefined}
          aria-modal="true"
          onClick={requestClose}
          // 첫 버튼이 아니라 시트 자체에 포커스를 둔다 — 열자마자 「로그아웃」에 포커스가 가면 안 된다.
          onOpenAutoFocus={(e) => {
            e.preventDefault()
            sheetRef.current?.focus()
          }}
          className="fixed inset-0 z-50 outline-none"
        >
          <Dialog.Title className="sr-only">{label}</Dialog.Title>
          {/* 넓은 화면에선 바닥 시트가 아니라 화면 가운데 창이다 — 끌 수 없는 손잡이를 달지 않는다. */}
          {/* 계정·지도 정보는 넓은 화면에서 이 창 대신 버튼 아래 메뉴(MenuPopover)를 쓴다. */}
          <div className="absolute inset-x-0 bottom-0 md:pointer-events-none md:inset-0 md:flex md:items-center md:justify-center md:p-6">
            <div
              style={sheetStyle}
              className={`enter-sheet relative md:pointer-events-auto md:w-full md:max-w-[440px] ${
                dragY === null ? 'transition-[transform,translate,opacity] duration-200 ease-out motion-reduce:transition-none' : ''
              } ${closing ? 'translate-y-full md:translate-y-0 md:opacity-0' : ''}`}
              onClick={(e) => e.stopPropagation()}
              onTransitionEnd={(e) => closing && e.target === e.currentTarget && onClose()}
            >
              <Toaster controlsVisible={false} />
              {/* 홈 표시줄이 있으면 그만큼, 없으면 16px. */}
              <section
                ref={sheetRef}
                tabIndex={-1}
                className="max-h-[90dvh] overflow-y-auto rounded-t-2xl bg-white px-4 pb-[max(16px,env(safe-area-inset-bottom))] pt-2 outline-none md:max-h-[85dvh] md:rounded-2xl md:p-5"
              >
                {/* 손잡이 줄만 끌린다 — 내용까지 끌게 하면 긴 목록(지역 고르기)의 스크롤과 부딪힌다. Esc·딤으로도 닫힌다. */}
                <div
                  aria-hidden="true"
                  className="-mx-4 -mt-2 flex h-7 cursor-grab touch-none items-center justify-center md:hidden"
                  onPointerDown={(e) => {
                    startY.current = e.clientY
                    setDragY(0)
                    e.currentTarget.setPointerCapture(e.pointerId)
                  }}
                  onPointerMove={(e) => dragY !== null && setDragY(e.clientY - startY.current)}
                  onPointerUp={onHandleUp}
                  onPointerCancel={() => setDragY(null)}
                >
                  <div className="h-1 w-12 rounded-full bg-ink-300" />
                </div>
                {children}
              </section>
            </div>
          </div>
          {overlay && <div onClick={(e) => e.stopPropagation()}>{overlay}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
