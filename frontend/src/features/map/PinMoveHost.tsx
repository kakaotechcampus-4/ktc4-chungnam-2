import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQueryClient } from '@tanstack/react-query'

import { nearestPlaces } from '@/features/search/api'
import { pinErrorMessage, toSearchResult, type PlaceSearchResultDto } from '@/features/search/model'
import ModalSheet from '@/features/shell/ModalSheet'
import { showToast } from '@/features/shell/toast'
import { josaRo } from '@/ui/josa'
import SheetTitle from '@/ui/SheetTitle'

import type { Pin } from './model'
import { mapBridge, usePinDragStore, type LatLng, type PinDrag } from './pinDrag'
import { moveBlockedReason, movePin, moveTargets, undoMove } from './pinMove'
import { usePinSelection } from './usePinSelection'

/** 들어가기(미끄러지기 + 한 번 튀기)와 돌아가기 시간(ms). Ghost(TrashDropZone)의 transition 과 같다. */
export const LAND_MS = 200 + 400
export const BACK_MS = 250
/** 끄는 손이 이만큼(ms) 멈추면 그 자리의 옮길 곳을 미리 찾는다. */
const PREVIEW_WAIT_MS = 250

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/**
 * 핀 끌어 옮기기(#1549)를 맡는다. 지도 화면에 하나만 둔다.
 * - 끄는 동안: 손이 멈춘 자리의 옮길 곳(우리 DB 장소, 100m 안)에 원을 미리 보인다.
 * - 지도 위에 놓으면: 옮길 곳이 1곳이면 바로 옮기고, 여러 곳이면 고르게 하고, 0곳이면 이유를 알리고 제자리로 돌린다.
 * - 옮길 수 없는 핀(남이 찍은 핀, 확정 핀, AI 추천 핀)은 이유를 알리고 제자리로 돌린다.
 * 옮긴 뒤 알림의 되돌리기는 새 핀을 지우고 옛 핀을 되살린다.
 */
export default function PinMoveHost({ mapId }: { mapId: string }) {
  const queryClient = useQueryClient()
  const drag = usePinDragStore((s) => s.drag)
  const set = usePinDragStore((s) => s.set)
  const { selectedPinId, selectPin } = usePinSelection()
  const [choose, setChoose] = useState<{ pin: Pin; places: PlaceSearchResultDto[]; at: LatLng } | null>(null)
  const handled = useRef<PinDrag | null>(null)
  const latest = useRef({ selectedPinId, selectPin })
  useEffect(() => {
    latest.current = { selectedPinId, selectPin }
  })

  /** 그림을 집은 자리로 돌려보내고 원래 핀을 다시 보인다. */
  const goBack = (d: PinDrag) => {
    if (reduced()) {
      d.release()
      return set(null)
    }
    set({ ...d, phase: 'back' })
    window.setTimeout(() => {
      d.release()
      if (usePinDragStore.getState().drag?.phase === 'back') set(null)
    }, BACK_MS)
  }

  /** 옮기고 알린다. 그림이 남아 있으면(놓자마자 옮긴 경우) 새 자리로 들어가게 한다. */
  const run = async (pin: Pin, place: PlaceSearchResultDto, d: PinDrag | null) => {
    try {
      const created = await movePin(queryClient, mapId, pin, place)
      const name = created.place_name ?? place.place_name
      if (latest.current.selectedPinId === pin.id) latest.current.selectPin(created.id)
      showToast(`${name}${josaRo(name)} 옮겼어요`, {
        label: '되돌리기',
        onClick: () =>
          void undoMove(queryClient, mapId, created, pin)
            .then(() => showToast('옮기기를 되돌렸어요'))
            .catch(() => showToast('옮기기를 되돌리지 못했어요')),
      })
      if (!d) return
      const to = mapBridge()?.toScreen(place)
      if (reduced() || !to) return set(null)
      set({ ...d, phase: 'land', to })
      window.setTimeout(() => usePinDragStore.getState().drag?.phase === 'land' && set(null), LAND_MS)
    } catch (err) {
      showToast(pinErrorMessage(err))
      if (d) goBack(d)
    }
  }

  // 지도 위에 놓았다.
  useEffect(() => {
    if (drag?.phase !== 'move' || !drag.at || handled.current === drag) return
    handled.current = drag
    const d = drag
    const blocked = moveBlockedReason(d.pin)
    if (blocked) {
      showToast(blocked)
      return goBack(d)
    }
    nearestPlaces(d.at!)
      .then((found) => {
        const places = moveTargets(d.pin, found)
        if (places.length === 0) {
          showToast('여기엔 옮길 수 있는 장소가 없어요')
          return goBack(d)
        }
        if (places.length === 1) return run(d.pin, places[0], d)
        goBack(d)
        setChoose({ pin: d.pin, places, at: d.at! })
      })
      .catch(() => {
        showToast('옮길 장소를 찾지 못했어요')
        goBack(d)
      })
    // run, goBack 은 매 렌더 새로 만들어지지만 store 와 ref 만 본다.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag])

  return (
    <>
      {drag?.phase === 'drag' && !drag.over && !moveBlockedReason(drag.pin) && <TargetPreview drag={drag} />}
      {choose && (
        <ModalSheet label="옮길 장소 고르기" onClose={() => setChoose(null)}>
          <SheetTitle>어디로 옮길까요?</SheetTitle>
          <p className="mb-3 mt-1 text-sm text-ink-500">놓은 자리 가까이에 장소가 여러 곳 있어요</p>
          <ul className="space-y-2">
            {choose.places.map((p) => {
              const r = toSearchResult(p, choose.at, [])
              return (
                <li key={p.place_id}>
                  <button
                    type="button"
                    onClick={() => {
                      setChoose(null)
                      void run(choose.pin, p, null)
                    }}
                    className="press w-full rounded-xl border border-ink-200 p-3 text-left"
                  >
                    <p className="truncate font-bold text-ink-900">{r.name}</p>
                    <p className="truncate text-xs text-ink-500">{r.meta}</p>
                  </button>
                </li>
              )
            })}
          </ul>
        </ModalSheet>
      )}
    </>
  )
}

/** 손이 멈춘 자리에 놓으면 들어갈 장소를 원으로 미리 보인다. 가장 가까운 한 곳이다. */
function TargetPreview({ drag }: { drag: PinDrag }) {
  const [spot, setSpot] = useState<{ x: number; y: number } | null>(null)
  const { x, y, pin } = drag
  useEffect(() => {
    let stale = false
    const t = window.setTimeout(() => {
      const at = mapBridge()?.toLatLng(x, y)
      if (!at) return setSpot(null)
      nearestPlaces(at)
        .then((found) => {
          if (stale) return
          const first = moveTargets(pin, found)[0]
          setSpot(first ? (mapBridge()?.toScreen(first) ?? null) : null)
        })
        .catch(() => !stale && setSpot(null))
    }, PREVIEW_WAIT_MS)
    return () => {
      stale = true
      window.clearTimeout(t)
    }
  }, [x, y, pin])
  if (!spot) return null
  return createPortal(
    <span
      aria-hidden="true"
      className="enter-fade pointer-events-none fixed left-0 top-0 z-[55] size-10 rounded-full border-2 border-brand-600 bg-brand-50/60"
      style={{ transform: `translate(${spot.x - 20}px, ${spot.y - 20}px)` }}
    />,
    document.body,
  )
}
