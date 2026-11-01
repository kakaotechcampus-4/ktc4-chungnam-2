import { createRoot } from 'react-dom/client'

import TestAdWindow from '@/ui/TestAdWindow'

import type { AdOutcome, LoadedAd } from './index'

/**
 * 테스트 광고(provider = fake, 로컬·스테이징). 실제 광고 SDK 처럼 앱의 React 트리 밖에 제 창을 띄운다.
 * 앱 트리 안(포털)에 그리면 클릭이 React 트리를 따라 올라가 뒤의 모달 시트(코스 시트)를 닫는다 — 그래서 따로 그린다.
 */
export function loadFakeAd(): LoadedAd {
  let used = false
  return {
    show: ({ seconds }) =>
      new Promise<AdOutcome>((resolve) => {
        if (used) return resolve('error') // 한 번 보인 광고는 다시 쓰지 않는다(LoadedAd 계약)
        used = true
        const host = document.createElement('div')
        document.body.appendChild(host)
        const root = createRoot(host)
        const finish = (outcome: AdOutcome) => {
          // 창 안의 클릭 처리 중에 그 루트를 지우지 않는다 — 처리가 끝난 뒤 지운다.
          queueMicrotask(() => {
            root.unmount()
            host.remove()
            resolve(outcome)
          })
        }
        try {
          root.render(<TestAdWindow seconds={seconds} onClose={(finished) => finish(finished ? 'viewed' : 'dismissed')} />)
        } catch {
          finish('error')
        }
      }),
  }
}
