import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { CONTROLS } from './layout'

import { TOAST_MS, useToastStore } from './toast'

/**
 * 시트 윗변 12px 위, 가로 가운데(Figma 참고 섹션). 최대 폭 361 = 화면 − 16×2.
 * 넘치면 두 줄, 그래도 넘치면 …로 줄인다. 동작 글자는 줄이지 않는다.
 * 지도 버튼 묶음과 겹치면 옆으로 비키지 않고 묶음 위로 올린다.
 */
export default function Toaster({ controlsVisible }: { controlsVisible: boolean }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [overlaps, setOverlaps] = useState(false)
  const toast = useToastStore((s) => s.toast)
  const dismiss = useToastStore((s) => s.dismiss)
  const [leavingId, setLeavingId] = useState<number | null>(null)

  useEffect(() => {
    if (!toast) return
    const ms = toast.action ? TOAST_MS.withAction : TOAST_MS.plain
    const fade = setTimeout(() => setLeavingId(toast.id), ms)
    const gone = setTimeout(() => dismiss(toast.id), ms + 300)
    return () => {
      clearTimeout(fade)
      clearTimeout(gone)
    }
  }, [toast, dismiss])

  // 가운데 놓인 토스트 양옆 여백이 버튼 묶음 자리(오른쪽 여백 + 버튼 폭 + 틈)보다 좁으면 겹친다.
  useLayoutEffect(() => {
    const w = boxRef.current?.offsetWidth ?? 0
    setOverlaps((window.innerWidth - w) / 2 < CONTROLS.right + CONTROLS.size + 8)
  }, [toast])

  if (!toast) return null
  const raised = controlsVisible && overlaps
  const leaving = leavingId === toast.id

  return (
    <div
      role="status"
      style={{ bottom: `calc(100% + 12px${raised ? ` + ${CONTROLS.stackHeight}px` : ''})` }}
      className={`pointer-events-none absolute inset-x-4 flex justify-center transition-opacity duration-300 ${
        leaving ? 'opacity-0' : 'opacity-100'
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
