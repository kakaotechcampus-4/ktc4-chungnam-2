import { useLayoutEffect, useRef, useState } from 'react'

import { CONTROLS } from './layout'

import { useToastStore } from './toast'

/**
 * 시트 윗변 12px 위, 가로 가운데(Figma 참고 섹션). 최대 폭 361 = 화면 − 16×2.
 * 넘치면 두 줄, 그래도 넘치면 …로 줄인다. 동작 글자는 줄이지 않는다.
 * 지도 버튼 묶음과 겹치면 옆으로 비키지 않고 묶음 위로 올린다.
 */
/**
 * `inside` 면 시트 윗변 위가 아니라 시트 안 아래쪽(AI 버튼 위)에 띄운다 — 3단계처럼 시트 위에 자리가 없을 때.
 */
export default function Toaster({ controlsVisible, inside = false }: { controlsVisible: boolean; inside?: boolean }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [overlaps, setOverlaps] = useState(false)
  const toast = useToastStore((s) => s.toast)
  const dismiss = useToastStore((s) => s.dismiss)
  // 가운데 놓인 토스트 양옆 여백이 버튼 묶음 자리(오른쪽 여백 + 버튼 폭 + 틈)보다 좁으면 겹친다.
  useLayoutEffect(() => {
    const w = boxRef.current?.offsetWidth ?? 0
    setOverlaps((window.innerWidth - w) / 2 < CONTROLS.right + CONTROLS.size + 8)
  }, [toast])

  if (!toast) return null
  const raised = controlsVisible && overlaps

  return (
    <div
      role="status"
      style={{ bottom: inside ? 48 : `calc(100% + 12px${raised ? ` + ${CONTROLS.stackHeight}px` : ''})` }}
      className={`pointer-events-none absolute inset-x-4 z-10 flex justify-center transition-opacity duration-300 ${
        toast.leaving ? 'opacity-0' : 'opacity-100'
      }`}
    >
      <div
        ref={boxRef}
        className="pointer-events-auto flex max-w-[361px] items-center gap-3 rounded-xl bg-[#3A3F4B]/82 px-4 py-2.5 text-sm text-white backdrop-blur-[12px]">
        <span className="line-clamp-2 [text-wrap:balance]">{toast.message}</span>
        {toast.action && (
          <button
            type="button"
            onClick={() => {
              toast.action?.onClick()
              dismiss(toast.id)
            }}
            className="shrink-0 font-semibold text-brand-300"
          >
            {toast.action.label}
          </button>
        )}
      </div>
    </div>
  )
}
