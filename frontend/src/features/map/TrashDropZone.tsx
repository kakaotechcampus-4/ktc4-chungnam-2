import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { binCenter, usePinDragStore, type PinDrag } from './pinDrag'
import { useTrashPinMutation } from './queries'
import { usePinSelection } from './usePinSelection'

/** 놓은 핀이 통으로 들어가는 시간, 그 뒤 뚜껑이 닫히는 시간(ms). 합쳐 0.5초 이하(DESIGN Motion). */
const SWALLOW_MS = 250
const CLOSE_MS = 200

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * 핀을 끌 때만 나타나는 휴지통(#1012). 자리는 토스트와 같다 — 모바일은 시트 윗변 12px 위 가운데(`above`),
 * 3단계처럼 시트 위에 지도가 없으면 시트 안 아래쪽(`inside`), 넓은 화면은 지도 영역 바닥 16px 위 가운데(`docked`).
 * 지도 버튼(오른쪽)과 겹치지 않는다. 위에 핀이 오면 테두리가 brand-600 이 되고 뚜껑이 열린다.
 * 놓으면 바로 지우고(확인 창 없음, 되돌리기 알림은 useTrashPinMutation), 핀이 작아지며 들어간 뒤 뚜껑이 닫힌다.
 * 포인터 전용이다. 키보드·스크린리더는 핀 상세의 「핀 삭제」를 쓴다.
 */
export default function TrashDropZone({ mapId, placement }: { mapId: string; placement: 'above' | 'inside' | 'docked' }) {
  const drag = usePinDragStore((s) => s.drag)
  const clear = usePinDragStore((s) => s.set)
  const trash = useTrashPinMutation(mapId)
  const { selectedPinId, selectPin } = usePinSelection()
  const [closing, setClosing] = useState(false)
  const handled = useRef<PinDrag | null>(null)

  // 지우기에 쓰는 값은 최신만 본다 — effect 가 mutation 상태가 바뀔 때마다 다시 돌면 타이머가 지워진다.
  const latest = useRef({ trash, selectedPinId, selectPin })
  useLayoutEffect(() => {
    latest.current = { trash, selectedPinId, selectPin }
  })

  useEffect(() => {
    if (drag?.phase !== 'drop') return
    // StrictMode 에서 effect 가 두 번 돌아도 한 번만 지운다.
    if (handled.current !== drag) {
      handled.current = drag
      const { trash, selectedPinId, selectPin } = latest.current
      trash.mutate(drag.pin, {
        onSuccess: () => drag.pin.id === selectedPinId && selectPin(null),
        onError: drag.release,
      })
    }
    if (reduced()) return clear(null)
    const t1 = setTimeout(() => setClosing(true), SWALLOW_MS)
    const t2 = setTimeout(() => {
      setClosing(false)
      clear(null)
    }, SWALLOW_MS + CLOSE_MS)
    return () => {
      clearTimeout(t1)
      clearTimeout(t2)
    }
  }, [drag, clear])

  if (!drag) return null
  const open = drag.over && !closing
  const bottom = placement === 'docked' ? 16 : placement === 'inside' ? 48 : 'calc(100% + 12px)'
  return (
    <>
      <div style={{ bottom }} className="pointer-events-none absolute inset-x-4 z-20 flex justify-center" aria-hidden="true">
        <div
          data-trash-bin
          className={`enter-pop flex h-12 items-center gap-2 rounded-full border-2 px-4 text-sm font-bold shadow-float transition-colors duration-200 ${
            drag.over ? 'border-brand-600 bg-brand-50 text-selected' : 'border-transparent bg-surface text-ink-700'
          }`}
        >
          <TrashCan open={open} />
          {drag.over ? '놓으면 삭제' : '삭제하기'}
        </div>
      </div>
      {createPortal(<Ghost drag={drag} />, document.body)}
    </>
  )
}

/** 손을 따라오는 핀. 끝(아래 가운데)이 손끝에 온다 — 터치는 손가락에 가리지 않게 조금 위다. 놓으면 휴지통 가운데로 작아지며 들어간다. */
function Ghost({ drag }: { drag: PinDrag }) {
  const dropping = drag.phase === 'drop'
  const to = dropping ? binCenter() : null
  const x = to?.x ?? drag.x
  const y = to ? to.y + 22 : drag.y - (drag.touch ? 24 : 0)
  return (
    <div
      aria-hidden="true"
      className="pointer-events-none fixed left-0 top-0 z-[60] size-11"
      style={{
        transform: `translate(${x - 22}px, ${y - 44}px) scale(${dropping ? 0.3 : 1})`,
        opacity: dropping ? 0 : 1,
        transition: dropping ? `transform ${SWALLOW_MS}ms cubic-bezier(0, 0, 0.2, 1), opacity ${SWALLOW_MS}ms` : undefined,
      }}
    >
      {/* 마크업은 pinMarker 가 만든 모양·색뿐이다(핀 이름은 넣지 않는다). */}
      <div className="pin-wobble flex size-full items-end justify-center" dangerouslySetInnerHTML={{ __html: drag.ghost }} />
    </div>
  )
}

/** lucide Trash2 의 선 경로. 뚜껑(윗줄·손잡이)만 따로 묶어 연다. */
function TrashCan({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <g className="trash-lid" data-open={open}>
        <path d="M3 6h18" />
        <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
      </g>
      <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
      <path d="M10 11v6" />
      <path d="M14 11v6" />
    </svg>
  )
}
