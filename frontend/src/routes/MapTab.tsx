import { useCallback, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import Pingo from '@/ui/Pingo'
import EmptyMap from '@/features/map/EmptyMap'
import { OnboardingBody, OnboardingHeader, type OnboardingKind } from '@/features/map/Onboarding'
import { filterPins } from '@/features/map/model'
import { CategoryChips, PinFilterBar } from '@/features/map/PinFilterControls'
import PinList, { PinListSkeleton } from '@/features/map/PinList'
import { usePinFilters } from '@/features/map/usePinFilters'
import PinSheet, { PinUnavailableSheet } from '@/features/map/PinSheet'
import { usePinSelection } from '@/features/map/usePinSelection'
import { usePinsQuery } from '@/features/map/queries'
import { useMapQuery, useMembersQuery } from '@/features/maps/queries'
import { useSheetStore } from '@/features/shell/sheetStore'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'

/**
 * 마킹된 장소 탭은 조립만 한다. 실제 내용은 전부 `features/map/` 안에 있다.
 * 새 기능은 이 파일을 키우지 말고 `features/map/` 에 파일을 더해서 여기서 끼운다.
 */
export default function MapTab() {
  const { mapId } = useShell()
  const { selectedPinId, selectPin } = usePinSelection()
  const { data: pins, isPending, error } = usePinsQuery(mapId)
  const setStage = useSheetStore((s) => s.setStage)
  const stage = useSheetStore((s) => s.stages.map)
  const map = useMapQuery(mapId).data
  const mapTitle = map?.title
  const memberCount = map?.memberCount ?? 0
  const members = useMembersQuery(mapId).data ?? []
  const { filters, setFilter, clear } = usePinFilters()
  const shown = pins && filterPins(pins, filters)
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

  if (onboarding && mapTitle) {
    return (
      <TabSheet tab="map" header={<OnboardingHeader kind={onboarding} mapTitle={mapTitle} />}>
        <OnboardingBody kind={onboarding} onDone={closeOnboarding} />
      </TabSheet>
    )
  }

  if (selectedPin) {
    return (
      <TabSheet tab="map" header={<SheetTitle>{selectedPin.place_name ?? '핀 상세'}</SheetTitle>}>
        <PinSheet pin={selectedPin} onClose={() => selectPin(null)} />
      </TabSheet>
    )
  }

  return (
    <TabSheet
      tab="map"
      header={
        <>
          <SheetTitle>마킹된 장소</SheetTitle>
          {stage === 3 && <CategoryChips value={filters.category} onChange={(c) => setFilter('category', c)} className="mt-2" />}
          {pins && pins.length > 0 && <PinFilterBar filters={filters} members={members} pins={pins} onChange={setFilter} />}
          <p className="mt-2 text-xs text-ink-500">{isPending ? '불러오는 중…' : `${shown?.length ?? 0}곳`}</p>
        </>
      }
    >
      {unavailable && <PinUnavailableSheet onClose={() => selectPin(null)} />}
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
    <div className="flex flex-col items-center py-6 text-center">
      <Pingo size={48} />
      <p className="mt-3 font-semibold text-ink-900">필터에 걸리는 핀이 없어요</p>
      <p className="mt-1 text-sm text-ink-500">{what} 핀은 아직 없어요</p>
      <button type="button" onClick={onClear} className="mt-4 rounded-lg border border-brand-600 px-4 py-2 text-sm font-semibold text-brand-600">
        필터 해제
      </button>
    </div>
  )
}

function SheetTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="truncate text-xl font-bold text-ink-900">{children}</h2>
}
