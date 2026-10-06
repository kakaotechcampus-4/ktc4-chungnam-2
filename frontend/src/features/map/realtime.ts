import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useMeQuery } from '@/features/auth/queries'
import { mapKeys } from '@/features/maps/queries'
import { showToast } from '@/features/shell/toast'

import type { Pin } from './model'
import { pinKeys } from './queries'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/** reconnecting = 브라우저가 알아서 다시 붙는 중, closed = 포기함(사람이 다시 연결을 눌러야 한다). */
/** 새로고침·닫기로 페이지를 떠날 때 브라우저가 연결을 끊는 건 장애가 아니다 — 그때는 끊김으로 알리지 않는다. */
let leaving = false
window.addEventListener('pagehide', () => (leaving = true))
export const isPageLeaving = () => leaving

export type ConnectionState = 'open' | 'reconnecting' | 'closed'

/**
 * 지도 전체 채널(docs/events.md). 받은 이벤트를 핀 캐시에 바로 반영한다.
 * 같은 이벤트가 두 번 올 수 있어(at-least-once) 모든 적용을 멱등하게 한다 — 핀은 id로 덮어쓰고,
 * 반응은 매번 집계 전체를 덮는다.
 * 연결이 끊기면 브라우저가 Last-Event-ID 로 다시 붙는다. 그동안 화면에 "다시 연결하는 중"을 띄운다.
 */
export function useMapEvents(mapId: string): { state: ConnectionState; reconnect: () => void } {
  const queryClient = useQueryClient()
  const myUserId = useMeQuery().data?.id
  const [state, setState] = useState<ConnectionState>('open')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const key = pinKeys.list(mapId)
    const source = new EventSource(`${BASE_URL}/maps/${mapId}/events`, { withCredentials: true })
    const update = (fn: (pins: Pin[]) => Pin[]) => queryClient.setQueryData<Pin[]>(key, (pins) => pins && fn(pins))
    const parse = <T>(e: MessageEvent) => JSON.parse(e.data) as T

    const upsert = (e: MessageEvent) => {
      const pin = parse<Pin>(e)
      const known = queryClient.getQueryData<Pin[]>(key)?.some((p) => p.id === pin.id)
      update((pins) => (known ? pins.map((p) => (p.id === pin.id ? pin : p)) : [...pins, pin]))
      if (!known && e.type === 'pin.created' && pin.created_by !== myUserId) {
        showToast(`${pin.created_by_display_name ?? '구성원'}님이 ${pin.place_name ?? '새 장소'} 핀을 찍었어요`)
      }
    }
    const remove = (e: MessageEvent) => {
      const { pin_id } = parse<{ pin_id: string }>(e)
      update((pins) => pins.filter((p) => p.id !== pin_id))
    }
    const reaction = (e: MessageEvent) => {
      const { pin_id, reaction_summary } = parse<{ pin_id: string; reaction_summary: Pin['reaction_summary'] }>(e)
      const before = queryClient.getQueryData<Pin[]>(key)?.find((p) => p.id === pin_id)
      // 내가 남긴 의견은 이미 캐시에 반영돼 집계가 같다. 다를 때만 남이 남긴 것으로 보고 알린다.
      // ponytail: 이벤트에 누가 남겼는지가 없어 "지우님이 반대" 같은 문구는 못 쓴다. 페이로드에 user 가 생기면 그 문구로.
      if (before && JSON.stringify(before.reaction_summary) !== JSON.stringify(reaction_summary)) {
        showToast(`${before.place_name ?? '핀'}에 새 의견이 올라왔어요`)
      }
      update((pins) => pins.map((p) => (p.id === pin_id ? { ...p, reaction_summary } : p)))
    }
    const members = () => void queryClient.invalidateQueries({ queryKey: mapKeys.detail(mapId) })

    source.addEventListener('pin.created', upsert)
    source.addEventListener('pin.published', upsert)
    source.addEventListener('pin.deleted', remove)
    source.addEventListener('reaction.changed', reaction)
    source.addEventListener('member.joined', members)
    source.onopen = () => setState('open')
    source.onerror = () => {
      if (leaving) return
      // CLOSED 는 브라우저가 재연결을 포기한 상태(인증 실패 등). 조용히 넘기지 않는다.
      if (source.readyState === EventSource.CLOSED) {
        console.error('[realtime] 실시간 연결이 닫혔어요', mapId)
        setState('closed')
      } else {
        setState('reconnecting')
      }
    }
    return () => source.close()
  }, [mapId, myUserId, queryClient, attempt])

  const reconnect = () => {
    // 끊긴 동안 놓친 변화는 이벤트로 다시 오지 않을 수 있어 목록을 새로 받는다.
    void queryClient.invalidateQueries({ queryKey: pinKeys.list(mapId) })
    setAttempt((n) => n + 1)
  }

  return { state, reconnect }
}
