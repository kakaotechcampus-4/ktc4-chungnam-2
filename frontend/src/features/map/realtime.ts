import { useEffect, useState } from 'react'
import { useQueryClient, type InvalidateQueryFilters } from '@tanstack/react-query'
import { useNavigate } from 'react-router'

import { useMeQuery } from '@/features/auth/queries'
import { mapKeys } from '@/features/maps/queries'
import { recommendKeys } from '@/features/recommend/queries'
import { showToast } from '@/features/shell/toast'
import { shortlistKeys } from '@/features/shortlist/queries'

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
const REACTION_WORD: Record<ReactionType, string> = { like: '좋음', against: '반대' }

/**
 * docs/events.md "이벤트별로 화면이 다시 받을 것"(#449) 그대로. 이벤트나 화면 데이터를 더하면 events.md 표와 같이 고친다.
 * 키는 앞부분이 같으면 함께 무효화된다(TanStack) — 지도 상세는 구성원, 핀 목록은 집계까지 덮지만 표대로 다 적는다.
 * agent.* 는 #536에서 더한다.
 */
function refetchTable(mapId: string): Record<string, InvalidateQueryFilters[]> {
  const pins = { queryKey: pinKeys.list(mapId) }
  const counts = { queryKey: pinKeys.counts(mapId) }
  const map = { queryKey: mapKeys.detail(mapId) }
  const members = { queryKey: mapKeys.members(mapId) }
  const myMaps = { queryKey: mapKeys.all, exact: true }
  // 추천 준비는 "의견이 달린 핀 1개"(#360)라 핀·의견 하나로 바뀐다.
  const readiness = { queryKey: recommendKeys.readiness(mapId) }
  return {
    'pin.created': [counts],
    'pin.published': [counts],
    // 분류가 바뀌었을 때만 필요하지만 페이로드에 예전 분류가 없어 늘 다시 받는다.
    // 확정 리스트는 핀을 따로 들고 있어 실시간 핀 승격(#777)으로 이름이 바뀌면 다시 받는다(#786).
    'pin.updated': [counts, readiness, { queryKey: shortlistKeys.list(mapId) }],
    'pin.deleted': [counts, readiness],
    'reaction.changed': [counts, readiness],
    'member.joined': [map, members],
    // 누가 나가면 그 사람의 의견이 지워진다.
    'member.left': [pins, counts, map, members, readiness],
    'owner.changed': [map, members],
    'map.updated': [map, myMaps],
    'map.deleted': [myMaps],
    // 확정 리스트와 동선은 다른 구성원이 바꿀 수 있다(5-10).
    'shortlist.changed': [{ queryKey: shortlistKeys.list(mapId) }, pins],
    'route.recalculated': [{ queryKey: shortlistKeys.route(mapId) }],
  }
}

/**
 * 지도 전체 채널(docs/events.md). 받은 이벤트를 핀 캐시에 바로 반영한다.
 * 같은 이벤트가 두 번 올 수 있어(at-least-once) 모든 적용을 멱등하게 한다 — 핀은 id로 덮어쓰고,
 * 반응은 매번 집계 전체를 덮는다.
 * 연결이 끊기면 브라우저가 Last-Event-ID 로 다시 붙는다. 그동안 화면에 "다시 연결하는 중"을 띄운다.
 */
export function useMapEvents(mapId: string): { state: ConnectionState; reconnect: () => void } {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const myUserId = useMeQuery().data?.id
  const [state, setState] = useState<ConnectionState>('open')
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    const key = pinKeys.list(mapId)
    // 서버가 지도 삭제로 닫은 연결은 에러로 보지 않는다. 페이지를 떠나는 중(leaving)과는 따로 둔다.
    let closedByServer = false
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
      // 내 의견은 이미 캐시에 반영했다 — 알리지 않는다. 사유는 이벤트에 없다.
      if (pin && user_id !== myUserId) {
        const who = `${display_name ?? '구성원'}님이 ${pin.place_name ?? '핀'}`
        showToast(type ? `${who}에 ${REACTION_WORD[type]} 의견을 남겼어요` : `${who} 의견을 거뒀어요`)
      }
      update((pins) => pins.map((p) => (p.id === pin_id ? { ...p, reaction_summary } : p)))
      // 열려 있는 핀 상세의 의견 목록 — 키가 페이로드의 핀이라 표에 두지 않는다.
      void queryClient.invalidateQueries({ queryKey: pinKeys.reactions(pin_id) })
    }
    // 지도가 삭제됐다 — 이 화면에 더 둘 게 없다. 서버가 구독도 닫는다.
    const mapDeleted = () => {
      closedByServer = true
      source.close()
      showToast('방장이 이 지도를 삭제했어요')
      queryClient.removeQueries({ queryKey: mapKeys.detail(mapId) })
      navigate('/', { replace: true })
    }

    // 페이로드로 바로 고치는 것(핀 한 개, 토스트). 나머지는 refetchTable 표대로 다시 받는다.
    const apply: Record<string, (e: MessageEvent) => void> = {
      'pin.created': upsert,
      'pin.published': upsert,
      'pin.updated': upsert,
      'pin.deleted': remove,
      'reaction.changed': reaction,
      'map.deleted': mapDeleted,
    }
    const table = refetchTable(mapId)
    for (const type of new Set([...Object.keys(apply), ...Object.keys(table)])) {
      source.addEventListener(type, (e) => {
        apply[type]?.(e as MessageEvent)
        for (const filters of table[type] ?? []) void queryClient.invalidateQueries(filters)
      })
    }
    source.onopen = () => setState('open')
    source.onerror = () => {
      if (leaving || closedByServer) return
      // CLOSED 는 브라우저가 재연결을 포기한 상태(인증 실패 등). 조용히 넘기지 않는다.
      if (source.readyState === EventSource.CLOSED) {
        console.error('[realtime] 실시간 연결이 닫혔어요', mapId)
        setState('closed')
      } else {
        setState('reconnecting')
      }
    }
    return () => source.close()
  }, [mapId, myUserId, queryClient, navigate, attempt])

  const reconnect = () => {
    // 끊긴 동안 놓친 변화는 이벤트로 다시 오지 않을 수 있어 목록을 새로 받는다.
    void queryClient.invalidateQueries({ queryKey: pinKeys.list(mapId) })
    setAttempt((n) => n + 1)
  }

  return { state, reconnect }
}
