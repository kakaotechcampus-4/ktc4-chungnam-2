import { useState, type ReactNode } from 'react'

import BottomSheet from './BottomSheet'
import MapControls from './MapControls'
import { useShell } from './shellContext'
import { useSheetStore, type TabKey } from './sheetStore'
import { TriangleAlert } from 'lucide-react'

import type { ConnectionState } from '@/features/map/realtime'

import Toaster from './Toaster'

/**
 * 탭 하나의 바텀시트. 탭 컴포넌트는 제목 줄(header)과 본문만 넘긴다 —
 * 단계 기억·지도 버튼·토스트 자리는 여기서 탭 3개가 똑같이 갖는다.
 */
export default function TabSheet({
  tab,
  header,
  expandOnScroll,
  children,
}: {
  tab: TabKey
  header: ReactNode
  /** 2단계에서 내용을 끌면 3단계로 올라간다(핀 상세 — 최종기획안 4절). */
  expandOnScroll?: boolean
  children: ReactNode
}) {
  const { activeControl, onControl, connection } = useShell()
  const stage = useSheetStore((s) => s.stages[tab])
  const setStage = useSheetStore((s) => s.setStage)
  const mapMoving = useSheetStore((s) => s.mapMoving)
  const modalOpen = useSheetStore((s) => s.modalOpen)

  // 3단계·모달, 그리고 검색창·칩과 시트 사이가 버튼 묶음보다 좁으면 숨긴다(Figma 참고 '지도 버튼 규칙', #308).
  const [cramped, setCramped] = useState(false)
  const controlsHidden = stage === 3 || modalOpen || cramped

  return (
    <BottomSheet
      stage={stage}
      onStageChange={(next) => setStage(tab, next)}
      header={header}
      expandOnScroll={expandOnScroll}
      banner={connection.state !== 'open' && <ConnectionBanner state={connection.state} onReconnect={connection.reconnect} />}
      top={
        <>
          <MapControls hidden={controlsHidden} fading={mapMoving} active={activeControl} onPress={onControl} onCrampedChange={setCramped} />
          {!modalOpen && <Toaster controlsVisible={!controlsHidden && !mapMoving} inside={stage === 3} />}
        </>
      }
    >
      {children}
    </BottomSheet>
  )
}

/**
 * 연결 끊김 띠(#299). 지도 위에 띄우면 핀·지도 버튼을 가리고, 노란 면은 확정 골드와 겹친다.
 * 그래서 시트 윗변에 회색 띠로 붙이고 문구를 자르지 않는다.
 */
function ConnectionBanner({ state, onReconnect }: { state: Exclude<ConnectionState, 'open'>; onReconnect: () => void }) {
  return (
    <div role="status" className="flex items-center gap-2 rounded-t-2xl bg-ink-100 px-4 py-1.5 text-xs font-medium text-ink-700">
      <TriangleAlert size={14} className="shrink-0 text-[var(--warn-line)]" aria-hidden="true" />
      {state === 'reconnecting' ? (
        '연결이 끊겼어요. 다시 연결하는 중…'
      ) : (
        <>
          <span className="flex-1">연결이 끊겼어요</span>
          <button type="button" onClick={onReconnect} className="hit-44 font-bold text-brand-600">
            다시 연결
          </button>
        </>
      )}
    </div>
  )
}
