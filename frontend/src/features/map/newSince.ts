import { useEffect } from 'react'
import { useQueries, useQuery, useQueryClient } from '@tanstack/react-query'

import { fetchMapNews, fetchReasonChips, markMapSeen, type MapNewsDto } from './api'
import { asReactionType, type Pin, type PinCategory, type ReactionDto, type ReactionType, type ReasonChip } from './model'
import { pinKeys } from './queries'

/**
 * 마지막으로 본 뒤 새로 생긴 핀과 의견(#1454). 무엇이 새것인지는 서버가 정한다(#1556).
 * 지도를 열면 GET /maps/{mapId}/news 를 한 번 받고, 이번에 연 동안은 그 값으로 그린다.
 * '확인'을 누르거나 지도를 떠나면 POST /maps/{mapId}/seen 으로 본 때를 적는다. 본 때는 받아 둔 소식의 as_of 다(#1672).
 * 기기와 상관없이 한 사람에 하나라 PC에서 확인하면 휴대폰의 표시도 사라진다.
 */
export type PinNews = {
  /** 지난번 뒤에 남이 찍은 핀. */
  newPin: boolean
  /** 지난번 뒤에 남이 남기거나 바꾼 의견. */
  opinions: ReactionDto[]
}

export const newsKey = (mapId: string) => ['maps', mapId, 'news'] as const

/** 서버 응답을 핀마다 묶는다. 지금 지도에 없는 핀(그새 지워짐)은 뺀다. */
export function toPinNews(news: MapNewsDto, pins: Pin[]): Map<string, PinNews> {
  const out = new Map<string, PinNews>()
  const here = new Set(pins.map((p) => p.id))
  const entry = (id: string) => out.get(id) ?? out.set(id, { newPin: false, opinions: [] }).get(id)!
  for (const id of news.new_pin_ids) if (here.has(id)) entry(id).newPin = true
  for (const r of news.new_reactions) if (here.has(r.pin_id)) entry(r.pin_id).opinions.push(r)
  return out
}

const WORD: Record<ReactionType, string> = { like: '좋음', against: '반대' }
/** 카드 한 장에 다는 줄은 이만큼. 넘치면 '외 N개'로 접는다. */
const MAX_LINES = 2

/** 카드에 다는 새 의견 줄. 예: 김도현님 반대 · 비싸요. 사유는 글이 있으면 글, 없으면 첫 칩. */
export function newsLines(
  n: PinNews,
  nameOf: (r: ReactionDto) => string,
  chipLabel: (id: string) => string | undefined,
): string[] {
  const lines = n.opinions.map((r) => {
    const type = asReactionType(r.type) ?? 'like'
    const reason = r.reason_text || (r.reason_chip_ids?.[0] && chipLabel(r.reason_chip_ids[0]))
    return [`${nameOf(r)}님 ${WORD[type]}`, reason].filter(Boolean).join(' · ')
  })
  return lines.length > MAX_LINES ? [...lines.slice(0, MAX_LINES - 1), `외 ${lines.length - MAX_LINES + 1}개`] : lines
}

/** 새 의견이 몇 개인지(배너 숫자). */
export const opinionCount = (n: PinNews) => n.opinions.length

/**
 * 마커(MapLayout)와 목록(MapTab)이 같은 값을 본다. 같은 쿼리 키라 한 번만 받는다.
 * 이번에 연 동안은 다시 받지 않는다 — 보는 사이 표시가 바뀌지 않게. 떠날 때 캐시를 지워 다음에 새로 받는다.
 * 처음 연 지도는 since 가 null 이라 아무것도 표시하지 않는다.
 */
export function useNewSince(mapId: string, pins: Pin[] | undefined, myId: string | undefined) {
  const news = useQuery({ queryKey: newsKey(mapId), queryFn: () => fetchMapNews(mapId), enabled: Boolean(myId), staleTime: Infinity, refetchOnWindowFocus: false })
  const byPin = news.data && pins ? toPinNews(news.data, pins) : new Map<string, PinNews>()

  const categories = [...new Set((pins ?? []).filter((p) => byPin.get(p.id)?.opinions.length).map((p) => p.category))]
  const chips = useQueries({
    queries: categories.map((c) => ({ queryKey: pinKeys.chips(c), queryFn: () => fetchReasonChips(c), staleTime: Infinity })),
  })
  const chipLabel = (category: PinCategory, id: string) =>
    (chips[categories.indexOf(category)]?.data as ReasonChip[] | undefined)?.find((c) => c.id === id)?.label

  const queryClient = useQueryClient()
  /** '확인' — 본 때를 적고 표시를 모두 지운다. 적기에 실패해도 이번 화면에서는 지운다(다음에 들어오면 다시 보인다). */
  function dismiss() {
    if (!news.data) return
    void markMapSeen(mapId, news.data.as_of).catch((err) => console.error('[newSince] 본 때를 적지 못했어요', err))
    queryClient.setQueryData<MapNewsDto>(newsKey(mapId), (d) => d && { ...d, new_pin_ids: [], new_reactions: [], truncated: false })
  }

  return { since: news.data?.since ?? null, news: byPin, truncated: news.data?.truncated ?? false, chipLabel, dismiss }
}

/**
 * 지도를 떠날 때(다른 화면으로 가거나 탭과 앱을 내릴 때) 본 때를 적는다. MapLayout 에 한 번만 둔다.
 * 새 소식을 받아 보기 전에 떠나면 적지 않는다 — 보지 못한 소식이 그대로 사라지지 않게.
 */
export function useSaveSeenOnLeave(mapId: string, myId: string | undefined) {
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!myId) return
    const save = () => {
      const seen = queryClient.getQueryData<MapNewsDto>(newsKey(mapId))
      if (!seen) return
      void markMapSeen(mapId, seen.as_of, { keepalive: true }).catch((err) => console.error('[newSince] 본 때를 적지 못했어요', err))
    }
    const onHide = () => document.visibilityState === 'hidden' && save()
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      save()
      queryClient.removeQueries({ queryKey: newsKey(mapId) })
    }
  }, [mapId, myId, queryClient])
}
