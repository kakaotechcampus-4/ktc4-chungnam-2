import { useEffect, useState, type ReactNode } from 'react'

import BottomSheet from './BottomSheet'
import MapControls from './MapControls'
import { useShell } from './shellContext'
import { useSheetStore, type TabKey } from './sheetStore'
import { useIsDesktop } from './useIsDesktop'
import { TriangleAlert } from 'lucide-react'

import AgentButton from '@/features/agent/AgentButton'
import type { ConnectionState } from '@/features/map/realtime'
import TrashDropZone from '@/features/map/TrashDropZone'

import Toaster from './Toaster'

/**
 * 탭 하나의 바텀시트. 탭 컴포넌트는 제목 줄(header)과 본문만 넘긴다 —
 * 단계 기억·지도 버튼·「핑고 AI 조언」·토스트 자리는 여기서 탭 4개가 똑같이 갖는다.
 * 넓은 화면에서는 지도 버튼·토스트·연결 띠를 지도 영역에 두므로(MapLayout) 시트에 붙이지 않는다(#338).
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
  const { mapId, activeControl, onControl, connection } = useShell()
  const desktop = useIsDesktop()
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
      banner={!desktop && connection.state !== 'open' && <ConnectionBanner state={connection.state} onReconnect={connection.reconnect} />}
      top={
        !desktop && (
          <>
            <MapControls hidden={controlsHidden} fading={mapMoving} active={activeControl} onPress={onControl} onCrampedChange={setCramped} />
            {/* 「핑고 AI 조언」은 지도 왼쪽 아래(agent-v2 16.1). 조언은 지도 단위라 지도가 떠 있는 네 탭 모두에 있다(#1162). */}
            <AgentButton mapId={mapId} hidden={controlsHidden} fading={mapMoving} />
            {!modalOpen && <Toaster controlsVisible={!controlsHidden && !mapMoving} inside={stage === 3} />}
            {/* 핀을 끌 때만 나타나는 휴지통(#1012). 토스트와 같은 자리 규칙이다. */}
            <TrashDropZone mapId={mapId} placement={stage === 3 ? 'inside' : 'above'} />
          </>
        )
      }
    >
      {children}
    </BottomSheet>
  )
}

/** 끊긴 뒤 이만큼 지나도 다시 붙지 않았을 때만 띠를 띄운다 — 휴대폰은 와이파이↔LTE 전환에도 잠깐 끊겼다 붙는다. */
const SHOW_AFTER_MS = 2500

/**
 * 연결 끊김 띠(#299). 지도 위에 띄우면 핀·지도 버튼을 가리고, 노란 면은 확정 골드와 겹친다.
 * 그래서 휴대폰은 시트 윗변에 회색 띠로 붙이고 문구를 자르지 않는다.
 * 넓은 화면은 시트 윗변이 없어서 지도 영역 위쪽 가운데, 칩 줄 아래에 떠 있는 띠(`floating`)로 둔다(#338, #1575).
 * - 자동으로 다시 붙는 중(reconnecting): 2.5초 지나도 끊겨 있을 때만 차분하게 알린다. 모달로 막지 않는다 — 실시간 소식만 멈출 뿐 화면은 그대로 쓸 수 있다.
 * - 다시 붙기를 포기함(closed): 바로, 「다시 연결」 버튼과 함께 굵게.
 * 연결되면 부르는 쪽이 그리지 않는다(다시 끊기면 시계가 새로 돈다).
 */
export function ConnectionBanner({
  state,
  onReconnect,
  floating = false,
}: {
  state: Exclude<ConnectionState, 'open'>
  onReconnect: () => void
  floating?: boolean
}) {
  const [late, setLate] = useState(false)
  useEffect(() => {
    const t = setTimeout(() => setLate(true), SHOW_AFTER_MS)
    return () => clearTimeout(t)
  }, [])
  if (state === 'reconnecting' && !late) return null
  return (
    <div
      role="status"
      className={`flex items-center gap-2 bg-ink-100 px-4 py-1.5 text-xs text-ink-700 ${floating ? 'pointer-events-auto rounded-xl shadow-float' : 'rounded-t-2xl'}`}
    >
      <TriangleAlert size={14} className="shrink-0 text-[var(--warn-line)]" aria-hidden="true" />
      {state === 'reconnecting' ? (
        <span className="font-medium">연결이 끊겼어요. 다시 연결하는 중…</span>
      ) : (
        <>
          <span className="flex-1 font-bold text-ink-900">연결이 끊겼어요</span>
          <button type="button" onClick={onReconnect} className="hit-44 font-bold text-brand-600">
            다시 연결
          </button>
        </>
      )}
    </div>
  )
}
