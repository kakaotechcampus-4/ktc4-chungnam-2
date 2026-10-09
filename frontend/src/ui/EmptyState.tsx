import type { ReactNode } from 'react'

import Pingo from './Pingo'

/** 목록이 비었을 때(빈 지도·필터 0곳·확정 0곳). 핑고 + 제목 + 설명 + 다음 행동 하나(#359). */
export default function EmptyState({ title, children, action }: { title: string; children: ReactNode; action: ReactNode }) {
  return (
    <div className="flex flex-col items-center py-6 text-center">
      <Pingo size={48} />
      <p className="mt-3 font-semibold text-ink-900">{title}</p>
      <p className="mt-1 text-sm text-ink-500">{children}</p>
      {/* flex 로 감싸 링크(<a>)도 버튼처럼 블록으로 선다. */}
      <div className="mt-4 flex">{action}</div>
    </div>
  )
}
