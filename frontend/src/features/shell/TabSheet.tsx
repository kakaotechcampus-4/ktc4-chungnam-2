import type { ReactNode } from 'react'

import BottomSheet from './BottomSheet'
import MapControls from './MapControls'
import { useShell } from './shellContext'
import { useSheetStore, type TabKey } from './sheetStore'
import Toaster from './Toaster'

/**
 * 탭 하나의 바텀시트. 탭 컴포넌트는 제목 줄(header)과 본문만 넘긴다 —
 * 단계 기억·지도 버튼·토스트 자리는 여기서 탭 3개가 똑같이 갖는다.
 */
export default function TabSheet({ tab, header, children }: { tab: TabKey; header: ReactNode; children: ReactNode }) {
  const { activeControl, onControl } = useShell()
  const stage = useSheetStore((s) => s.stages[tab])
  const setStage = useSheetStore((s) => s.setStage)
  const mapMoving = useSheetStore((s) => s.mapMoving)
  const modalOpen = useSheetStore((s) => s.modalOpen)

  // 3단계·모달에서는 지도 버튼을 숨긴다(Figma 참고 '지도 버튼 규칙').
  const controlsHidden = stage === 3 || modalOpen

  return (
    <BottomSheet
      stage={stage}
      onStageChange={(next) => setStage(tab, next)}
      header={header}
      top={
        <>
          <MapControls hidden={controlsHidden} fading={mapMoving} active={activeControl} onPress={onControl} />
          {!modalOpen && <Toaster controlsVisible={!controlsHidden && !mapMoving} />}
        </>
      }
    >
      {children}
    </BottomSheet>
  )
}
