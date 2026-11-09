import { create } from 'zustand'

/** 새 소식을 다는 탭. 지금은 AI 추천뿐이다 — AI 코스는 다른 탭에 있으면 진행 조회가 멈춰서 끝난 줄을 모른다(#1704). */
export type NewsTab = 'recommend'

/** `지도id:탭` → 말풍선 글. 화면 상태라 저장하지 않는다(새로고침하면 사라진다). */
const useTabNewsStore = create<{ news: Record<string, string> }>(() => ({ news: {} }))
const keyOf = (mapId: string, tab: NewsTab) => `${mapId}:${tab}`

/**
 * 그 탭에 새 소식을 단다(#1704, 배지) — 아래 탭 막대에 귤색 점과 잠깐 뜨는 말풍선, 넓은 화면 패널 탭에는 점.
 * 그 탭을 보고 있으면 달지 않는다 — 화면이 이미 결과로 바뀐다.
 */
export function markTabNews(mapId: string, tab: NewsTab, message: string) {
  if (window.location.pathname.startsWith(`/maps/${mapId}/${tab}`)) return
  useTabNewsStore.setState((s) => ({ news: { ...s.news, [keyOf(mapId, tab)]: message } }))
}

/** 그 탭에 들어오면 지운다. */
export function clearTabNews(mapId: string, tab: NewsTab) {
  const key = keyOf(mapId, tab)
  if (!(key in useTabNewsStore.getState().news)) return
  useTabNewsStore.setState((s) => ({ news: Object.fromEntries(Object.entries(s.news).filter(([k]) => k !== key)) }))
}

export const useTabNews = (mapId: string, tab: string): string | undefined => useTabNewsStore((s) => s.news[`${mapId}:${tab}`])
