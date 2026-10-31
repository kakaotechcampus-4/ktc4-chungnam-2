import { useQueryClient } from '@tanstack/react-query'
import { ExternalLink } from 'lucide-react'

import { ApiError } from '@/api'
import { useCreatePinMutation } from '@/features/map/queries'
import type { CandidateDto, RecommendCategory } from '@/features/recommend/model'
import { pinErrorMessage } from '@/features/search/model'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'

import type { AdDto } from './api'
import { overlapsCandidate } from './model'
import { adKeys, recordClickOnce, useRecommendAds } from './queries'

/**
 * 추천 탭 맨 아래 광고 영역(docs/ads.md 4절). 추천 결과와 따로 놓인 흰 카드라 AI 후보 카드(brand-50)와 섞이지 않는다.
 * 광고는 필터를 거치지 않아서 이유·조건 체크·구성원 집계를 싣지 않는다. 0개면 그리지 않는다.
 * 탭을 연 뒤 나온 추천 결과에 같은 장소가 있으면 그 칸만 숨긴다(다른 광고로 채우지 않는다).
 */
export default function AdArea({ mapId, hide = [] }: { mapId: string; hide?: CandidateDto[] }) {
  const { ads: all, category } = useRecommendAds(mapId)
  const ads = all.filter((ad) => !hide.some((c) => overlapsCandidate(ad, c)))
  if (ads.length === 0) return null
  return (
    <section aria-label="광고" className="mt-6 space-y-2 border-t border-ink-200 pt-4">
      <p className="text-label text-ink-500">광고예요. 추천 조건으로 거른 장소가 아니에요</p>
      <ul className="space-y-2">
        {ads.map((ad) => (
          <li key={ad.ad_id}>
            <AdCard mapId={mapId} category={category} ad={ad} />
          </li>
        ))}
      </ul>
    </section>
  )
}

function AdCard({ mapId, category, ad }: { mapId: string; category: RecommendCategory | null; ad: AdDto }) {
  const queryClient = useQueryClient()
  const create = useCreatePinMutation(mapId)
  const { place } = ad

  const click = () => recordClickOnce(ad.ad_id, mapId)

  const markOnMap = () =>
    queryClient.setQueryData<{ ads: AdDto[] }>(adKeys.list(mapId, category), (d) =>
      d && { ads: d.ads.map((a) => (a.ad_id === ad.ad_id ? { ...a, on_map: true } : a)) },
    )

  function pinIt() {
    click()
    // 검색 결과와 같은 매칭 힌트 경로(#473). 광고 id는 싣지 않는다(docs/ads.md 2절 6번).
    create.mutate(
      { source: 'search', place_id: place.place_id, place_name: place.name, lat: place.lat, lng: place.lng, category: place.category },
      {
        onSuccess: (pin) => {
          const name = pin.place_name ?? place.name
          showToast(`${name}${josa(name, '을', '를')} 지도에 찍었어요`)
          markOnMap()
        },
        onError: (err) => {
          if (err instanceof ApiError && err.code === 'PIN_DUPLICATE') markOnMap()
          showToast(pinErrorMessage(err))
        },
      },
    )
  }

  return (
    <article className="space-y-1 rounded-xl bg-white p-3 ring-1 ring-ink-200">
      <header className="flex items-start gap-2">
        <h3 className="min-w-0 flex-1 truncate text-body font-semibold text-ink-900">{place.name}</h3>
        <span className="tag tag-neutral shrink-0">광고</span>
      </header>
      <p className="break-keep text-xs text-ink-500">{[place.category, place.address].filter(Boolean).join(' · ')}</p>
      <div className="flex items-center justify-between pt-1">
        {ad.on_map ? (
          <button type="button" disabled className="btn-neutral btn-sm">
            이미 지도에 있어요
          </button>
        ) : (
          <button type="button" disabled={create.isPending} onClick={pinIt} className="btn-outline btn-sm">
            {create.isPending ? '올리는 중…' : '지도에 올리기'}
          </button>
        )}
        {place.place_url && (
          <a href={place.place_url} target="_blank" rel="noopener noreferrer" onClick={click} className="btn-link inline-flex items-center gap-0.5 text-xs">
            카카오맵에서 보기 <ExternalLink size={12} aria-hidden="true" />
          </a>
        )}
      </div>
    </article>
  )
}
