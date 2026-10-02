import { useEffect, type ReactNode } from 'react'

import Toaster from './Toaster'

/**
 * 화면 바닥에 붙는 모달 시트(Figma 프로필·계정 시트). 검정 32% 딤이 하단 바까지 덮고, 딤을 누르거나 Esc 로 닫는다.
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
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50">
      <button type="button" aria-label="닫기" onClick={onClose} className="absolute inset-0 bg-black/32" />
      <div className="absolute inset-x-0 bottom-0">
        <Toaster controlsVisible={false} />
        <section
          role="dialog"
          aria-modal="true"
          aria-label={label}
          className="max-h-[90dvh] overflow-y-auto rounded-t-2xl bg-white px-4 pb-[34px] pt-2"
        >
          <div className="mx-auto mb-4 h-1 w-12 rounded-full bg-ink-300" aria-hidden="true" />
          {children}
        </section>
      </div>
      {overlay}
    </div>
  )
}
