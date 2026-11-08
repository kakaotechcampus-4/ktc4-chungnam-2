import { useEffect, useMemo, useRef } from 'react'
import { useQueries, useQueryClient } from '@tanstack/react-query'
import { create } from 'zustand'

import { fetchReactions, fetchReasonChips } from './api'
import { asReactionType, type Pin, type PinCategory, type ReactionDto, type ReactionType, type ReasonChip } from './model'
import { pinKeys } from './queries'

/**
 * 마지막으로 본 뒤 새로 생긴 핀·의견(#1454).
 *
 * 서버 의견에는 남긴 시각이 없어서, 지도를 떠날 때 핀마다 의견 수(와 아는 경우 누가 무엇을 남겼는지)를
 * 이 브라우저에 적어 두고 다음에 들어왔을 때 지금 의견 수와 견준다. 계정·지도마다 따로 둔다.
 * 의견 수가 늘어난 핀만 의견 목록을 한 번 더 불러와 이름과 사유를 붙인다.
 * 저장소가 막힌 브라우저에선 표시 없이 동작한다.
 */
export type Seen = {
  at: string
  pins: Record<string, { like: number; against: number; who?: Record<string, ReactionType> }>
}

export type PinNews = {
  /** 지난번에 없던 핀(내가 찍은 핀은 빼고). */
  newPin: boolean
  /** 누가 남긴 새 의견인지 아는 것. 내 의견은 뺀다. */
  opinions: ReactionDto[]
  /** 늘어난 건 알지만 누구 것인지 가릴 수 없는 수(의견 목록을 못 받았거나, 처음 보는 핀에서 일부만 늘었을 때). */
  counted: Partial<Record<ReactionType, number>>
}

const TYPES: ReactionType[] = ['like', 'against']

/** 지난번보다 어느 반응이든 수가 늘어난 핀. 줄기만 한 핀(의견을 거둠)은 소식이 아니다. */
export function changedPinIds(seen: Seen, pins: Pin[]): string[] {
  return pins.filter((p) => {
    const prev = seen.pins[p.id]
    return prev !== undefined && TYPES.some((t) => p.reaction_summary[t] > prev[t])
  }).map((p) => p.id)
}

export function diffSince(
  seen: Seen,
  pins: Pin[],
  myId: string,
  reactionsOf: (pinId: string) => ReactionDto[] | undefined,
): Map<string, PinNews> {
  const news = new Map<string, PinNews>()
  const changed = new Set(changedPinIds(seen, pins))
  for (const pin of pins) {
    const prev = seen.pins[pin.id]
    if (!prev) {
      // 휴지통에서 되살린 핀은 지난번에 없었어도 새 핀이 아니다 — 지도에 올라온 시각으로 가른다.
      if (pin.created_by !== myId && Date.parse(pin.created_at) > Date.parse(seen.at)) news.set(pin.id, { newPin: true, opinions: [], counted: {} })
      continue
    }
    if (!changed.has(pin.id)) continue
    const reactions = reactionsOf(pin.id)
    const opinions: ReactionDto[] = []
    const counted: PinNews['counted'] = {}
    for (const t of TYPES) {
      const grew = pin.reaction_summary[t] - prev[t]
      if (grew <= 0) continue
      const others = (reactions ?? []).filter((r) => r.user_id !== myId && asReactionType(r.type) === t)
      if (!reactions) counted[t] = grew
      else if (prev.who) opinions.push(...others.filter((r) => prev.who![r.user_id] !== t))
      // 누가 남겼는지 몰랐던 핀: 이 반응이 전부 새로 생긴 거면 다 새것, 일부만 늘었으면 수만 보인다.
      else if (others.length <= grew) opinions.push(...others)
      else counted[t] = grew
    }
    if (opinions.length || Object.keys(counted).length) news.set(pin.id, { newPin: false, opinions, counted })
  }
  return news
}

const WORD: Record<ReactionType, string> = { like: '좋음', against: '반대' }
/** 카드 한 장에 다는 줄은 이만큼. 넘치면 「외 N개」로 접는다. */
const MAX_LINES = 2

/** 카드에 다는 새 의견 줄 — 「김도현님 반대 · 비싸요」, 누구 것인지 모르면 「반대 +1」. 사유는 글이 있으면 글, 없으면 첫 칩. */
export function newsLines(
  n: PinNews,
  nameOf: (r: ReactionDto) => string,
  chipLabel: (id: string) => string | undefined,
): string[] {
  const lines = [
    ...n.opinions.map((r) => {
      const type = asReactionType(r.type) ?? 'like'
      const reason = r.reason_text || (r.reason_chip_ids?.[0] && chipLabel(r.reason_chip_ids[0]))
      return [`${nameOf(r)}님 ${WORD[type]}`, reason].filter(Boolean).join(' · ')
    }),
    ...TYPES.flatMap((t) => (n.counted[t] ? [`${WORD[t]} +${n.counted[t]}`] : [])),
  ]
  return lines.length > MAX_LINES ? [...lines.slice(0, MAX_LINES - 1), `외 ${lines.length - MAX_LINES + 1}개`] : lines
}

/** 새 의견이 몇 개인지(배너 숫자). */
export const opinionCount = (n: PinNews) => n.opinions.length + TYPES.reduce((sum, t) => sum + (n.counted[t] ?? 0), 0)

/** 지금 모습을 적는다. 의견 목록을 이미 받아 둔 핀(상세를 열어 본 핀 등)은 누가 무엇을 남겼는지도 같이 둔다. */
export function snapshotOf(pins: Pin[], reactionsOf: (pinId: string) => ReactionDto[] | undefined, now = new Date()): Seen {
  const out: Seen['pins'] = {}
  for (const p of pins) {
    const reactions = reactionsOf(p.id)
    const who = reactions && Object.fromEntries(reactions.flatMap((r) => (asReactionType(r.type) ? [[r.user_id, r.type as ReactionType]] : [])))
    out[p.id] = { like: p.reaction_summary.like, against: p.reaction_summary.against, ...(who ? { who } : {}) }
  }
  return { at: now.toISOString(), pins: out }
}

const storageKey = (key: string) => `seenPins:${key}`

function read(key: string): Seen | null {
  try {
    const v = JSON.parse(localStorage.getItem(storageKey(key)) ?? 'null') as Seen | null
    return v && typeof v.at === 'string' && typeof v.pins === 'object' ? v : null
  } catch {
    return null
  }
}

function write(key: string, seen: Seen) {
  try {
    localStorage.setItem(storageKey(key), JSON.stringify(seen))
  } catch {
    // 위 주석 — 표시 없이 동작한다
  }
}

/** 이번에 지도를 연 동안 견줄 기준. 지도를 떠날 때 지우고, 다음에 들어오면 저장소에서 다시 읽는다. */
const useBaseStore = create<{ base: Record<string, Seen | null> }>(() => ({ base: {} }))
const setBase = (key: string, seen: Seen | null | undefined) =>
  useBaseStore.setState((s) => {
    const base = { ...s.base }
    if (seen === undefined) delete base[key]
    else base[key] = seen
    return { base }
  })

/**
 * 마커(MapLayout)와 목록(MapTab)이 같은 값을 본다. 의견 목록·사유 칩은 같은 쿼리 키라 한 번만 받는다.
 * 처음 연 지도는 견줄 것이 없어 아무것도 표시하지 않는다.
 */
export function useNewSince(mapId: string, pins: Pin[] | undefined, myId: string | undefined) {
  const key = myId ? `${myId}:${mapId}` : null
  const base = useBaseStore((s) => (key ? s.base[key] : undefined))
  useEffect(() => {
    if (key && !(key in useBaseStore.getState().base)) setBase(key, read(key))
  }, [key])

  const list = useMemo(() => pins ?? [], [pins])
  const changed = useMemo(() => (base ? changedPinIds(base, list) : []), [base, list])
  const reactions = useQueries({
    queries: changed.map((id) => ({ queryKey: pinKeys.reactions(id), queryFn: () => fetchReactions(id) })),
  })
  const categories = [...new Set(list.filter((p) => changed.includes(p.id)).map((p) => p.category))]
  const chips = useQueries({
    queries: categories.map((c) => ({ queryKey: pinKeys.chips(c), queryFn: () => fetchReasonChips(c), staleTime: Infinity })),
  })

  const reactionsOf = (id: string) => reactions[changed.indexOf(id)]?.data
  const news = base && myId ? diffSince(base, list, myId, reactionsOf) : new Map<string, PinNews>()
  const chipLabel = (category: PinCategory, id: string) =>
    (chips[categories.indexOf(category)]?.data as ReasonChip[] | undefined)?.find((c) => c.id === id)?.label

  const queryClient = useQueryClient()
  /** 「확인」 — 지금 모습을 기준으로 삼아 표시를 모두 지운다. */
  function dismiss() {
    if (!key) return
    const seen = snapshotOf(list, (id) => queryClient.getQueryData<ReactionDto[]>(pinKeys.reactions(id)))
    write(key, seen)
    setBase(key, seen)
  }

  return { since: base?.at ?? null, news, chipLabel, dismiss }
}

/**
 * 지도를 떠날 때(다른 화면으로 가거나 탭·앱을 내릴 때) 지금 모습을 적는다. MapLayout 에 한 번만 둔다.
 * 이번에 연 동안의 표시는 그대로 두고, 화면을 떠나면 기준을 지워 다음에 들어올 때 새로 읽게 한다.
 */
export function useSaveSeenOnLeave(mapId: string, pins: Pin[] | undefined, myId: string | undefined) {
  const queryClient = useQueryClient()
  const latest = useRef(pins)
  useEffect(() => {
    latest.current = pins
  })
  useEffect(() => {
    if (!myId) return
    const key = `${myId}:${mapId}`
    const save = () => {
      // 핀 목록을 받기 전에 떠나면 빈 모습을 적어 두지 않는다 — 그러면 다음에 모든 핀이 새 핀으로 보인다.
      if (latest.current) write(key, snapshotOf(latest.current, (id) => queryClient.getQueryData<ReactionDto[]>(pinKeys.reactions(id))))
    }
    const onHide = () => document.visibilityState === 'hidden' && save()
    document.addEventListener('visibilitychange', onHide)
    return () => {
      document.removeEventListener('visibilitychange', onHide)
      save()
      setBase(key, undefined)
    }
  }, [mapId, myId, queryClient])
}
