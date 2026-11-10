import { WifiOff } from 'lucide-react'

import EmptyState from './EmptyState'

const TITLE = '인터넷 연결이 끊겼어요'

/**
 * 인터넷이 끊겨 기다림이 멈췄을 때(#1722). 연결되면 멈춘 요청이 알아서 이어지므로 다시 시도 버튼은 두지 않는다.
 * 화면이나 목록 자리는 핑고 빈 화면, 칩이나 줄처럼 작은 자리는 `compact` 한 줄이다.
 */
export default function OfflineState({ compact = false }: { compact?: boolean }) {
  if (compact) {
    return (
      <p role="status" className="flex items-center gap-1.5 text-sm text-ink-500">
        <WifiOff size={16} aria-hidden="true" className="shrink-0" />
        {TITLE}
      </p>
    )
  }
  return (
    <div role="status">
      <EmptyState mood="sad" title={TITLE}>
        연결되면 자동으로 이어서 불러와요
      </EmptyState>
    </div>
  )
}
