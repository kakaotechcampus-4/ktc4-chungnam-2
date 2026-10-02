import { useOutletContext } from 'react-router'

import type { ControlKey } from './MapControls'

/** MapLayout 이 탭들에게 내려주는 것. 지도 버튼은 지도를 움직여야 해서 레이아웃이 들고 있다. */
export type ShellContext = {
  mapId: string
  activeControl: ControlKey | null
  onControl: (key: ControlKey) => void
}

export const useShell = () => useOutletContext<ShellContext>()
