import { useEffect, useRef, useState } from 'react'
import { useQueryClient, type InvalidateQueryFilters, type QueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router'

import { agentEventHandlers, agentKeys } from '@/features/agent/queries'
import { useMeQuery } from '@/features/auth/queries'
import { courseKeys } from '@/features/course/queries'
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

/**
 * 이벤트든 서버 ping(20초마다)이든 이만큼 아무것도 못 받으면 연결이 조용히 죽은 것으로 본다(docs/events.md 전달 보장 8번, #832).
 * 노트북 절전·Wi-Fi 전환·공유기의 유휴 연결 정리 뒤에는 브라우저가 끊긴 줄 모르고 「열림」으로 기다린다.
 */
export const STALE_MS = 60_000
const STALE_CHECK_MS = 10_000

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
 * agent.* 는 표가 아니라 페이로드로 고친다(apply, features/agent).
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
    // 되살린 핀이 확정이었으면 확정 리스트에 다시 올라간다(#864). 휴지통 목록에서도 빠진다.
    'pin.restored': [counts, readiness, { queryKey: shortlistKeys.list(mapId) }, { queryKey: pinKeys.trash(mapId) }],
    'reaction.changed': [counts, readiness],
    'member.joined': [map, members],
    // 누가 나가면 그 사람의 의견이 지워진다.
    'member.left': [pins, counts, map, members, readiness],
    'owner.changed': [map, members],
    // 날짜가 바뀌면 서버가 기간 밖 일정을 빼고 일정 version(기간 포함)도 바뀐다 — 확정 리스트 키 아래 일정도 다시 받는다(#1273).
    'map.updated': [map, myMaps, { queryKey: shortlistKeys.list(mapId) }],
    'map.deleted': [myMaps],
    // 확정 리스트는 다른 구성원이 바꿀 수 있다(5-10). 동선은 이 기기의 일정 순서라(2026-11-03) 서버 동선(route.recalculated)은 받지 않는다.
    // 일정도 이 이벤트로 바뀐다. 열려 있는 AI 코스 결과는 일정이 바뀌면 stale 이 되어 「반영」을 막아야 해서 최근 코스와 run 상세도 다시 받는다(#1322).
    'shortlist.changed': [{ queryKey: shortlistKeys.list(mapId) }, pins, { queryKey: courseKeys.latest(mapId) }, { queryKey: courseKeys.runs }],
  }
}

/**
 * 끊긴 동안 놓친 변화는 이벤트로 다시 오지 않을 수 있어 새로 받는다(docs/events.md 전달 보장 8번).
 * 열려 있는 AI 코스 결과도 다시 받는다 — 그동안 일정이 바뀌었으면 stale 로 「일정이 바뀌었어요」를 보여야 해서다(#1322).
 */
function refreshMap(queryClient: QueryClient, mapId: string) {
  for (const queryKey of [pinKeys.list(mapId), pinKeys.counts(mapId), shortlistKeys.list(mapId), courseKeys.latest(mapId), courseKeys.runs]) {
    void queryClient.invalidateQueries({ queryKey })
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
  // 사람이 「다시 연결」을 눌러 맺는 중인지. 그 연결이 또 실패하면 알린다.
  const manual = useRef(false)

  useEffect(() => {
    const key = pinKeys.list(mapId)
    // 서버가 지도 삭제로 닫은 연결은 에러로 보지 않는다. 페이지를 떠나는 중(leaving)과는 따로 둔다.
    let closedByServer = false
    const source = new EventSource(`${BASE_URL}/maps/${mapId}/events`, { withCredentials: true })
    // 핀 목록을 아직 받지 않았으면 고칠 게 없다 — 버리지 말고 새로 받게 한다(#832, 버리면 다시 받을 장치가 없었다).
    const update = (fn: (pins: Pin[]) => Pin[]) => {
      if (queryClient.getQueryData<Pin[]>(key)) queryClient.setQueryData<Pin[]>(key, (pins) => pins && fn(pins))
      else void queryClient.invalidateQueries({ queryKey: key })
    }
    // 마지막으로 무엇이든 받은 시각. 모든 이벤트·ping·연결 열림에서 고친다.
    let lastSeen = Date.now()
    const seen = () => (lastSeen = Date.now())
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
        showToast(type ? `${who}에 ${REACTION_WORD[type]} 의견을 남겼어요` : `${who}에 남긴 의견을 취소했어요`)
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
      queryClient.removeQueries({ queryKey: agentKeys.state(mapId) })
      navigate('/', { replace: true })
    }

    // 페이로드로 바로 고치는 것(핀 한 개, 토스트). 나머지는 refetchTable 표대로 다시 받는다.
    const apply: Record<string, (e: MessageEvent) => void> = {
      'pin.created': upsert,
      'pin.published': upsert,
      'pin.updated': upsert,
      'pin.restored': upsert,
      'pin.deleted': remove,
      'reaction.changed': reaction,
      'map.deleted': mapDeleted,
      // 내가 나갔다(다른 기기에서 나가기 등) — 그 지도의 핑고 AI 조언 상태를 버린다(agent-v2 16.4). 남이 나간 건 표대로 다시 받는다.
      'member.left': (e) => {
        if (parse<{ user_id: string }>(e).user_id === myUserId) queryClient.removeQueries({ queryKey: agentKeys.state(mapId) })
      },
      ...agentEventHandlers(queryClient, mapId),
    }
    const table = refetchTable(mapId)
    for (const type of new Set([...Object.keys(apply), ...Object.keys(table)])) {
      source.addEventListener(type, (e) => {
        seen()
        apply[type]?.(e as MessageEvent)
        for (const filters of table[type] ?? []) void queryClient.invalidateQueries(filters)
      })
    }
    // control 은 ping·replay_truncated 둘이다. 받은 것만 적고 type 은 보지 않는다(모르는 type 은 무시, events.md).
    source.addEventListener('control', seen)
    source.onopen = () => {
      seen()
      manual.current = false
      setState('open')
    }
    source.onerror = () => {
      if (leaving || closedByServer) return
      // CLOSED 는 브라우저가 재연결을 포기한 상태(인증 실패 등). 조용히 넘기지 않는다.
      if (source.readyState === EventSource.CLOSED) {
        console.error('[realtime] 실시간 연결이 닫혔어요', mapId)
        // 「다시 연결」을 눌렀는데 또 실패했다 — 띠만 돌아오면 눌러도 안 되는 것처럼 보인다.
        if (manual.current) showToast('아직 연결되지 않았어요. 잠시 뒤 다시 눌러 주세요')
        manual.current = false
        setState('closed')
      } else {
        setState('reconnecting')
      }
    }
    // 60초 동안 조용하면 닫고 새로 맺는다. 탭이 숨겨진 동안은 타이머가 늦게 돌아서, 다시 보일 때도 점검한다.
    // 브라우저가 재연결을 포기한(CLOSED) 연결은 인증 실패 같은 이유라 사람이 「다시 연결」을 누르는 쪽에 둔다.
    const check = () => {
      if (closedByServer || source.readyState === EventSource.CLOSED || Date.now() - lastSeen <= STALE_MS) return
      console.warn('[realtime] 60초 동안 받은 것이 없어 다시 연결해요', mapId)
      source.close()
      refreshMap(queryClient, mapId)
      setState('reconnecting')
      setAttempt((n) => n + 1)
    }
    const onVisible = () => document.visibilityState === 'visible' && check()
    const timer = setInterval(check, STALE_CHECK_MS)
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
      source.close()
    }
  }, [mapId, myUserId, queryClient, navigate, attempt])

  const reconnect = () => {
    refreshMap(queryClient, mapId)
    // Firefox 와 앞단 Caddy 를 거친 연결은 첫 데이터(서버 ping, 최대 20초)가 와야 열린다.
    // 그동안 버튼을 거둬 다시 눌러 처음부터 맺는 일을 막는다.
    manual.current = true
    setState('reconnecting')
    setAttempt((n) => n + 1)
  }

  return { state, reconnect }
}
