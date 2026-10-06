import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import EmptyState from '@/ui/EmptyState'
import EmptyMap from '@/features/map/EmptyMap'
import { OnboardingBody, OnboardingHeader, type OnboardingKind } from '@/features/map/Onboarding'
import { filterPins } from '@/features/map/model'
import { CategoryChips, PinFilterBar } from '@/features/map/PinFilterControls'
import PinList, { PinListSkeleton } from '@/features/map/PinList'
import { usePinFilters } from '@/features/map/usePinFilters'
import { PinDetailBody, PinDetailHeader } from '@/features/map/PinDetail'
import PinUnavailable from '@/features/map/PinUnavailable'
import { usePinSelection } from '@/features/map/usePinSelection'
import { useCountsQuery, usePinsQuery } from '@/features/map/queries'
import { useMapQuery, useMembersQuery } from '@/features/maps/queries'
import { usePlaceSearchQuery } from '@/features/search/queries'
import { SearchResultsBody, SearchResultsHeader } from '@/features/search/SearchResults'
import { useSearchStore } from '@/features/search/searchStore'
import { useSheetStore } from '@/features/shell/sheetStore'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { useIsDesktop } from '@/features/shell/useIsDesktop'

/**
 * 마킹된 장소 탭은 조립만 한다. 실제 내용은 전부 `features/map/` 안에 있다.
 * 새 기능은 이 파일을 키우지 말고 `features/map/` 에 파일을 더해서 여기서 끼운다.
 */
export default function MapTab() {
  const { mapId } = useShell()
  const { selectedPinId, selectPin } = usePinSelection()
  const { data: pins, isPending, error } = usePinsQuery(mapId)
  const counts = useCountsQuery(mapId).data
  const setStage = useSheetStore((s) => s.setStage)
  const stage = useSheetStore((s) => s.stages.map)
  const desktop = useIsDesktop()
  const map = useMapQuery(mapId).data
  const mapTitle = map?.title
  const memberCount = map?.memberCount ?? 0
  const members = useMembersQuery(mapId).data ?? []
  const { filters, setFilter, clear } = usePinFilters()
  const sorted = pins && filterPins(pins, filters)
  // 순서는 필터·정렬을 바꾸거나 핀이 늘고 줄 때만 다시 매긴다. 의견 수만 바뀌었을 땐 그대로 둬서
  // 방금 의견을 남긴 카드가 맨 위로 튀지 않게 한다(#308).
  const orderKey = sorted ? `${filters.category}|${filters.createdBy}|${filters.sort}|${sorted.map((p) => p.id).sort().join(',')}` : ''
  const [order, setOrder] = useState<{ key: string; ids: string[] } | null>(null)
  if (sorted && order?.key !== orderKey) setOrder({ key: orderKey, ids: sorted.map((p) => p.id) })
  const shown = sorted && order?.key === orderKey ? order.ids.map((id) => sorted.find((p) => p.id === id)).filter((p) => p !== undefined) : sorted
  const search = useSearchStore()
  const found = usePlaceSearchQuery(search.query, search.near).data
  const filtered = Boolean(filters.category || filters.createdBy)
  const [params, setParams] = useSearchParams()
  const onboarding = params.get('onboarding') as OnboardingKind | null

  const closeOnboarding = useCallback(() => {
    const next = new URLSearchParams(params)
    next.delete('onboarding')
    setParams(next, { replace: true })
  }, [params, setParams])

  // 온보딩은 시트 2단계로 띄우고, 접으면 닫힌다(Figma 3절 — 온보딩을 접으면 탭 1단계로).
  useEffect(() => {
    if (onboarding) setStage('map', 2)
  }, [onboarding, setStage])
  // "접었을 때"만 닫는다. 처음 들어올 때 이전 단계가 1이었던 건 접은 게 아니다.
  const prevStage = useRef(stage)
  useEffect(() => {
    if (onboarding && prevStage.current !== 1 && stage === 1) closeOnboarding()
    prevStage.current = stage
  }, [onboarding, stage, closeOnboarding])

  // 핀을 고르면 상세가 2단계로 올라온다(최종기획안 4절 "핀 상세").
  useEffect(() => {
    if (selectedPinId) setStage('map', 2)
  }, [selectedPinId, setStage])

  const selectedPin = pins?.find((pin) => pin.id === selectedPinId)
  // 목록을 다 받은 뒤에도 없으면 볼 수 없는 핀이다. 로딩 중이나 실패 중에는 판단하지 않는다.
  const unavailable = Boolean(selectedPinId) && !selectedPin && !isPending && !error

  // 검색은 잠깐 하는 작업이라 다른 화면(상세·온보딩)보다 앞에 온다. 닫으면 원래 화면으로 돌아간다.
  if (search.query) {
    return (
      <TabSheet tab="map" header={<SearchResultsHeader count={found ? found.length : null} />}>
        <SearchResultsBody mapId={mapId} pins={pins ?? []} />
      </TabSheet>
    )
  }

  if (onboarding && mapTitle) {
    return (
      <TabSheet tab="map" header={<OnboardingHeader kind={onboarding} mapTitle={mapTitle} />}>
        <OnboardingBody mapId={mapId} kind={onboarding} onDone={closeOnboarding} />
      </TabSheet>
    )
  }

  if (selectedPin) {
    return (
      <TabSheet
        tab="map"
        expandOnScroll
        header={<PinDetailHeader pin={selectedPin} mapId={mapId} onBack={() => selectPin(null)} />}
      >
        <PinDetailBody pin={selectedPin} mapId={mapId} members={members} onDone={() => selectPin(null)} />
      </TabSheet>
    )
  }

  return (
    <TabSheet
      tab="map"
      header={
        <>
          <SheetTitle>마킹된 장소</SheetTitle>
          {/* 넓은 화면은 단계가 없고 칩이 지도 영역 왼쪽 위에 있다(#338). */}
          {stage === 3 && !desktop && <CategoryChips value={filters.category} onChange={(c) => setFilter('category', c)} className="mt-2" />}
          {pins && pins.length > 0 && <PinFilterBar filters={filters} members={members} pins={pins} onChange={setFilter} />}
          <p className="mt-2 text-xs text-ink-500">
            {isPending ? '불러오는 중…' : `${shown?.length ?? 0}곳`}
            {counts && counts.members_total > 0 && (
              <span className="font-bold text-ink-600"> · {counts.members_with_opinion}/{counts.members_total}명이 의견을 남겼어요</span>
            )}
          </p>
        </>
      }
    >
      {unavailable && <PinUnavailable onClose={() => selectPin(null)} />}
      {isPending && <PinListSkeleton />}
      {error && <ErrorText message="핀을 불러오지 못했어요" error={error} />}
      {pins?.length === 0 && <EmptyMap />}
      {pins && pins.length > 0 && shown?.length === 0 && filtered && (
        <FilterEmpty who={members.find((m) => m.userId === filters.createdBy)?.name} category={filters.category} onClear={clear} />
      )}
      {shown && shown.length > 0 && <PinList pins={shown} memberCount={memberCount} onSelect={selectPin} />}
    </TabSheet>
  )
}

/** 필터 0곳(Figma) — 필터 때문에 비었다는 걸 알려주고 바로 풀 수 있게 한다. */
function FilterEmpty({ who, category, onClear }: { who?: string; category: string | null; onClear: () => void }) {
  const what = [who && `${who}님이 올린`, category].filter(Boolean).join(' ')
  return (
    <EmptyState
      title="필터에 걸리는 핀이 없어요"
      action={
        <button type="button" onClick={onClear} className="btn-outline px-4 py-2 text-sm">
          필터 해제
        </button>
      }
    >
      {what} 핀은 아직 없어요
    </EmptyState>
  )
}

function SheetTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="truncate text-xl font-bold text-ink-900">{children}</h2>
}
