import { useEffect, useLayoutEffect, useRef } from 'react'
import { create } from 'zustand'

import { josa } from '@/ui/josa'

type PanelBack = { label: string; onBack: () => void }

/**
 * 넓은 화면 패널 헤더 왼쪽 위 ‹ 가 할 일. 패널 안 이전 화면(핀 상세 → 목록 등)이 있을 때만 차 있다.
 * 지도 바꾸기·지도 목록은 헤더의 지도 제목 메뉴가 맡는다 — ‹ 는 패널 밖으로 나가지 않는다.
 */
export const usePanelBackStore = create<{ back: PanelBack | null }>(() => ({ back: null }))

/**
 * 넓은 화면이면 이 화면의 「이전 화면」을 패널 헤더 ‹ 에 건다. 화면이 사라지면 같이 뗀다.
 * `enabled` 가 false 면 걸지 않는다(모바일은 각 화면이 자기 자리에 ‹ 를 그린다).
 */
export function usePanelBack(label: string, onBack: () => void, enabled: boolean) {
  // onBack 은 렌더마다 새 함수라 effect 의존성에 두면 걸고 떼기를 되풀이한다. 마지막 것만 기억한다.
  const latest = useRef(onBack)
  useLayoutEffect(() => {
    latest.current = onBack
  })
  useEffect(() => {
    if (!enabled) return
    const entry: PanelBack = { label, onBack: () => latest.current() }
    usePanelBackStore.setState({ back: entry })
    // 다음 화면이 먼저 걸었으면 그대로 둔다.
    return () => {
      if (usePanelBackStore.getState().back === entry) usePanelBackStore.setState({ back: null })
    }
  }, [label, enabled])
}

/** 헤더 ‹ 의 스크린리더 이름 — 「마킹된 장소로 돌아가기」. */
export function backAriaLabel(label: string) {
  return `${label}${josa(label, '으로', '로')} 돌아가기`
}
