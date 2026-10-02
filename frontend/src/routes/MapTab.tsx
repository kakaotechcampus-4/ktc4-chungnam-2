import { useEffect } from 'react'

import ErrorText from '@/ErrorText'
import PinList from '@/features/map/PinList'
import PinSheet, { PinUnavailableSheet } from '@/features/map/PinSheet'
import { usePinSelection } from '@/features/map/usePinSelection'
import { usePinsQuery } from '@/features/map/queries'
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

  // 핀을 고르면 상세가 2단계로 올라온다(최종기획안 4절 "핀 상세").
  useEffect(() => {
    if (selectedPinId) setStage('map', 2)
  }, [selectedPinId, setStage])

  const selectedPin = pins?.find((pin) => pin.id === selectedPinId)
  // 목록을 다 받은 뒤에도 없으면 볼 수 없는 핀이다. 로딩 중이나 실패 중에는 판단하지 않는다.
  const unavailable = Boolean(selectedPinId) && !selectedPin && !isPending && !error

  if (selectedPin) {
    return (
      <TabSheet tab="map" header={<SheetTitle>{selectedPin.place_name ?? '핀 상세'}</SheetTitle>}>
        <PinSheet pin={selectedPin} onClose={() => selectPin(null)} />
      </TabSheet>
    )
  }

  return (
    <TabSheet tab="map" header={<SheetTitle>마킹된 장소</SheetTitle>}>
      {unavailable && <PinUnavailableSheet onClose={() => selectPin(null)} />}
      {isPending && <p className="text-sm text-ink-500">핀을 불러오는 중…</p>}
      {error && <ErrorText message="핀을 불러오지 못했어요" error={error} />}
      {pins?.length === 0 && (
        // docs/errors.md MAP_EMPTY. 핀 찍는 길 안내는 #290.
        <p className="text-sm text-ink-500">아직 아무도 핀을 찍지 않았어요</p>
      )}
      {pins && <PinList pins={pins} onSelect={selectPin} />}
    </TabSheet>
  )
}

function SheetTitle({ children }: { children: React.ReactNode }) {
  return <h2 className="truncate text-xl font-bold text-ink-900">{children}</h2>
}
