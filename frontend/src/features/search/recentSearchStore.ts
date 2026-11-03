import { useCallback, useState } from 'react'

/**
 * 최근 장소 검색어. 이 브라우저에만, 계정마다 따로 둔다(한 기기를 여럿이 쓰면 남의 검색어가 보이지 않게).
 * 검색어(사람이 친 글)만 남긴다 — 검색 결과(카카오 응답)는 저장하지 않는다(#53). 지도 링크는 남기지 않는다.
 * 저장소가 막힌 브라우저에선 기록 없이 동작한다.
 */
export const RECENT_MAX = 8
const keyOf = (userId: string) => `recentPlaceSearches:${userId}`

/** 맨 앞에 넣고, 같은 검색어는 앞으로 올리고, 8개만 남긴다. */
export function pushRecent(list: string[], query: string): string[] {
  return [query, ...list.filter((q) => q !== query)].slice(0, RECENT_MAX)
}

function read(userId: string): string[] {
  try {
    const v: unknown = JSON.parse(localStorage.getItem(keyOf(userId)) ?? '[]')
    return Array.isArray(v) ? v.filter((q): q is string => typeof q === 'string').slice(0, RECENT_MAX) : []
  } catch {
    return []
  }
}

function write(userId: string, list: string[]) {
  try {
    if (list.length) localStorage.setItem(keyOf(userId), JSON.stringify(list))
    else localStorage.removeItem(keyOf(userId))
  } catch {
    // 위 주석 — 기록 없이 동작한다
  }
}

/** userId가 아직 없으면(내 정보 받기 전) 기록을 쓰지도 보이지도 않는다. */
export function useRecentSearches(userId: string | undefined) {
  const [state, setState] = useState<{ userId?: string; list: string[] }>({ list: [] })
  if (state.userId !== userId) setState({ userId, list: userId ? read(userId) : [] })
  const list = state.userId === userId ? state.list : []

  const update = useCallback(
    (fn: (list: string[]) => string[]) => {
      if (!userId) return
      setState((s) => {
        const next = fn(s.list)
        write(userId, next)
        return { userId, list: next }
      })
    },
    [userId],
  )
  return {
    list,
    add: (q: string) => update((l) => pushRecent(l, q)),
    remove: (q: string) => update((l) => l.filter((x) => x !== q)),
    clear: () => update(() => []),
  }
}
