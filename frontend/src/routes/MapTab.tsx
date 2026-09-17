import { ApiError } from '@/api'
import MapCanvas from '@/features/map/MapCanvas'
import PinList from '@/features/map/PinList'
import PinSheet from '@/features/map/PinSheet'
import { useMapUiStore } from '@/features/map/mapStore'
import { usePins } from '@/features/map/usePins'

/**
 * 지도 탭은 조립만 한다. 실제 내용은 전부 `features/map/` 안에 있다 —
 * #17·#18·#19·#20·#21 이 동시에 붙는 화면이라, 한 파일에 모아두면 그 파일이 병목이 된다.
 * 새 기능은 이 파일을 키우지 말고 `features/map/` 에 파일을 더해서 여기서 끼운다.
 */
export default function MapTab() {
  const selectedPinId = useMapUiStore((s) => s.selectedPinId)
  const selectPin = useMapUiStore((s) => s.selectPin)

  const { data: pins, isPending, error } = usePins()
  const selectedPin = pins?.find((pin) => pin.id === selectedPinId)

  return (
    <div className="p-4">
      <MapCanvas pins={pins ?? []} onSelect={selectPin} />

      {isPending && <p className="text-sm text-muted-foreground">핀을 불러오는 중…</p>}

      {error && (
        <p className="text-sm text-destructive">
          핀을 불러오지 못했어요
          {error instanceof ApiError && (
            <span className="ml-1 font-mono text-xs">({error.code})</span>
          )}
        </p>
      )}

      {pins?.length === 0 && (
        // docs/errors.md MAP_EMPTY. 입력 경로 3개 안내는 #16.
        <p className="text-sm text-muted-foreground">아직 아무도 핀을 찍지 않았어요</p>
      )}

      {pins && <PinList pins={pins} onSelect={selectPin} />}

      {selectedPin && <PinSheet pin={selectedPin} onClose={() => selectPin(null)} />}
    </div>
  )
}
