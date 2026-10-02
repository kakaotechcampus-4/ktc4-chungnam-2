import { useCallback, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import EmptyMap from '@/features/map/EmptyMap'
import { OnboardingBody, OnboardingHeader, type OnboardingKind } from '@/features/map/Onboarding'
import PinList from '@/features/map/PinList'
import PinSheet, { PinUnavailableSheet } from '@/features/map/PinSheet'
import { usePinSelection } from '@/features/map/usePinSelection'
import { usePinsQuery } from '@/features/map/queries'
import { useMapQuery } from '@/features/maps/queries'
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
  const mapTitle = useMapQuery(mapId).data?.title
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
          {pins && <p className="text-xs text-ink-500">{pins.length}곳</p>}
        </>
      }
    >
      {unavailable && <PinUnavailableSheet onClose={() => selectPin(null)} />}
      {isPending && <p className="text-sm text-ink-500">핀을 불러오는 중…</p>}
      {error && <ErrorText message="핀을 불러오지 못했어요" error={error} />}
      {pins?.length === 0 && <EmptyMap />}
      {pins && <PinList pins={pins} onSelect={selectPin} />}
    </TabSheet>
  )
}

function SheetTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="truncate text-xl font-bold text-ink-900">{children}</h2>
}
