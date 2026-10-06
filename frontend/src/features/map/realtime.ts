import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { useMeQuery } from '@/features/auth/queries'
import { mapKeys } from '@/features/maps/queries'
import { showToast } from '@/features/shell/toast'

import type { Pin, ReactionType } from './model'
import { pinKeys } from './queries'

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? ''

/** reconnecting = 브라우저가 알아서 다시 붙는 중, closed = 포기함(사람이 다시 연결을 눌러야 한다). */
/** 새로고침·닫기로 페이지를 떠날 때 브라우저가 연결을 끊는 건 장애가 아니다 — 그때는 끊김으로 알리지 않는다. */
let leaving = false
window.addEventListener('pagehide', () => (leaving = true))
export const isPageLeaving = () => leaving

export type ConnectionState = 'open' | 'reconnecting' | 'closed'

/** docs/events.md — 삭제면 type 이 null 이다. 사유는 싣지 않는다. */
type ReactionChanged = {
  pin_id: string
  reaction_summary: Pin['reaction_summary']
  user_id: string
  display_name?: string
  type: ReactionType | null
}
const REACTION_WORD: Record<ReactionType, string> = { like: '좋음', neutral: '조율 필요', against: '반대' }

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
      const { pin_id, reaction_summary, user_id, display_name, type } = parse<ReactionChanged>(e)
      const pin = queryClient.getQueryData<Pin[]>(key)?.find((p) => p.id === pin_id)
      // 내 의견은 이미 캐시에 반영했다. 의견을 거둔 것(type=null)은 알리지 않는다.
      if (pin && type && user_id !== myUserId) {
        const place = pin.place_name ?? '핀'
        showToast(`${display_name ?? '구성원'}님이 ${place}에 ${REACTION_WORD[type]} 의견을 남겼어요`)
      }
      update((pins) => pins.map((p) => (p.id === pin_id ? { ...p, reaction_summary } : p)))
      // 의견을 남긴 사람 수(「2/4명」)와 열려 있는 핀 상세의 의견 목록이 바뀐다.
      void queryClient.invalidateQueries({ queryKey: pinKeys.counts(mapId) })
      void queryClient.invalidateQueries({ queryKey: pinKeys.reactions(pin_id) })
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
