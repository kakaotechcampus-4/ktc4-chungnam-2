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
}

export const useShell = () => useOutletContext<ShellContext>()
