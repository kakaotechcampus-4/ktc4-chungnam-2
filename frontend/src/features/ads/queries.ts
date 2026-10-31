import { useQuery } from '@tanstack/react-query'

import { useAiStore } from '@/features/recommend/aiStore'
import { chosenCategory, toReadinessCards, type RecommendCategory } from '@/features/recommend/model'
import { useReadinessQuery } from '@/features/recommend/queries'
import { useShell } from '@/features/shell/shellContext'

import { fetchAds, recordAdClick } from './api'

export const adKeys = { list: (mapId: string, category: RecommendCategory | null) => ['ads', mapId, category ?? 'all'] as const }

/** 이번 조회(탭을 연 동안) 안에서 클릭을 이미 보낸 광고. 새로 조회하면 비운다(docs/ads.md 4절 — 광고 하나당 한 번). */
const clicked = new Set<string>()

/**
 * 추천 탭 광고 조회. 조회 1번이 노출 1번으로 집계돼서(docs/ads.md 9절) 탭을 열 때와 카테고리가 바뀔 때만 부른다.
 * 카테고리는 화면이 보고 있는 것 — 추천 뒤에는 그 run 의 카테고리, 추천 전에는 준비 화면에서 고른 카테고리다.
 * 추천 탭이 탭을 연 동안 이 훅을 붙잡고 있어서, 안의 화면(준비 → 근거 → 진행 → 결과)이 바뀌어도 staleTime Infinity라 다시 부르지 않는다.
 * gcTime 0이라 탭을 닫으면 캐시가 지워져, 다시 열 때 그때의 지도 중심으로 새로 부른다.
 */
export function useRecommendAds(mapId: string) {
  const { getCenter } = useShell()
  const run = useAiStore((s) => s.runs[mapId])
  const picked = useAiStore((s) => s.picked[mapId])
  const readiness = useReadinessQuery(mapId)
  // 준비 상태를 받기 전에는 부르지 않는다(카테고리 없이 한 번, 받은 뒤 한 번 — 두 번 집계되지 않게).
  // 준비 상태를 못 받았으면 카테고리 없이 부른다 — 서버가 추천 대상 카테고리 전체에서 고른다.
  const category = run ? run.category : readiness.data ? chosenCategory(toReadinessCards(readiness.data), picked) : readiness.isError ? null : undefined
  const query = useQuery({
    queryKey: adKeys.list(mapId, category ?? null),
    queryFn: () => {
      const center = getCenter()
      if (!center) throw new Error('지도 중심을 아직 몰라요')
      clicked.clear()
      return fetchAds(mapId, category ?? null, center)
    },
    enabled: category !== undefined,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
  return { ads: query.data?.ads ?? [], category: category ?? null }
}

/** 클릭 기록은 이번 조회 안에서 광고 하나당 한 번. 실패는 사용자에게 알리지 않는다(docs/ads.md 4절) — 집계용이라 사용자가 할 일이 없다. */
export function recordClickOnce(adId: string, mapId: string) {
  if (clicked.has(adId)) return
  clicked.add(adId)
  recordAdClick(adId, mapId).catch(() => {})
}
