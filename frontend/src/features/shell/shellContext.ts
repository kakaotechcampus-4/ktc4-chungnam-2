import { useOutletContext } from 'react-router'

import type { ConnectionState } from '@/features/map/realtime'

import type { ControlKey } from './MapControls'

/** MapLayout 이 탭들에게 내려주는 것. 지도 버튼은 지도를 움직여야 해서 레이아웃이 들고 있다. */
export type ShellContext = {
  mapId: string
  activeControl: ControlKey | null
  onControl: (key: ControlKey) => void
  /** 실시간 연결. 끊기면 시트 윗변 띠로 알린다. */
  connection: { state: ConnectionState; reconnect: () => void }
  /** 지금 보이는 지도의 가운데(모바일은 시트에 가린 부분을 뺀다, #1331). 지도가 없으면 핀들의 위치 기준(livePlaceAnchor). 셸 밖 테스트만 null. */
  getCenter: () => { lat: number; lng: number } | null
  /** 지도를 여행 지역(지도 만들 때 고른 시·도)이 다 보이게 맞춘다. 경계가 없으면 지역 가운데로, 지역이 없으면 그대로다. */
  showRegion: () => void
}

export const useShell = () => useOutletContext<ShellContext>()
