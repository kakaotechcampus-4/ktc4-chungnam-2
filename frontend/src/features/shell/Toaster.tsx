import { useLayoutEffect, useRef, useState } from 'react'

import { CONTROLS } from './layout'

import { useToastStore } from './toast'

/**
 * 시트 윗변 12px 위, 가로 가운데(Figma 참고 섹션). 최대 폭 361 = 화면 − 16×2.
 * 넘치면 두 줄, 그래도 넘치면 …로 줄인다. 동작 글자는 줄이지 않는다.
 * 지도 버튼 묶음과 겹치면 묶음 위로 올린다. 올리면 검색창·칩을 덮을 만큼 자리가 없으면 올리지 않고,
 * 시트 윗변 위에 둔 채 폭을 버튼 묶음 왼쪽까지로 줄인다(넘치면 두 줄, #308).
 */
/**
 * `inside` 면 시트 윗변 위가 아니라 시트 안 아래쪽(AI 버튼 위)에 띄운다 — 3단계처럼 시트 위에 자리가 없을 때.
 */
export default function Toaster({ controlsVisible, inside = false }: { controlsVisible: boolean; inside?: boolean }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [mode, setMode] = useState<'center' | 'raised' | 'narrow'>('center')
  const toast = useToastStore((s) => s.toast)
  const dismiss = useToastStore((s) => s.dismiss)
  useLayoutEffect(() => {
    const box = boxRef.current
    if (!box || inside || !controlsVisible) return setMode('center')
    // 가운데 놓인 토스트 양옆 여백이 버튼 묶음 자리(오른쪽 여백 + 버튼 폭 + 틈)보다 좁으면 겹친다.
    if ((window.innerWidth - box.offsetWidth) / 2 >= CONTROLS.right + CONTROLS.size + 8) return setMode('center')
    const sheetTop = box.closest('section')?.getBoundingClientRect().top ?? 0
    const headerBottom = document.querySelector('[data-map-header]')?.getBoundingClientRect().bottom ?? 0
    const raisedTop = sheetTop - 12 - CONTROLS.stackHeight - box.offsetHeight
    setMode(raisedTop >= headerBottom + 8 ? 'raised' : 'narrow')
  }, [toast, inside, controlsVisible])

  if (!toast) return null

  return (
    <div
      role="status"
      style={{
        bottom: inside ? 48 : `calc(100% + 12px${mode === 'raised' ? ` + ${CONTROLS.stackHeight}px` : ''})`,
        // 좁힐 때는 버튼 묶음 왼쪽 8px까지만 쓴다.
        right: mode === 'narrow' ? CONTROLS.right + CONTROLS.size + 8 : undefined,
      }}
      className={`pointer-events-none absolute left-4 right-4 z-10 flex justify-center transition-opacity duration-300 ${
        toast.leaving ? 'opacity-0' : 'opacity-100'
      }`}
    >
      <div
        ref={boxRef}
        className="pointer-events-auto flex max-w-[361px] items-center gap-3 rounded-xl bg-[var(--toast-bg)] px-4 py-2.5 text-sm text-white backdrop-blur-[12px]">
        <span className="line-clamp-2 break-keep [text-wrap:balance]">{toast.message}</span>
        {toast.action && (
          <button
            type="button"
            onClick={() => {
              toast.action?.onClick()
              dismiss(toast.id)
            }}
            className="shrink-0 font-bold text-white underline underline-offset-2"
          >
            {toast.action.label}
          </button>
        )}
      </div>
    </div>
  )
}
