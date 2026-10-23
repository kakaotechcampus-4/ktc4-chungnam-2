import type { ReactNode } from 'react'

import Pingo, { type PingoMood } from './Pingo'

/**
 * 비어 있을 때(빈 지도·필터 0곳·확정 0곳·지도 0개·검색 0곳·끊긴 초대). 핑고 + 제목 + 설명 + 다음 행동 하나(#359).
 * 핑고는 서비스의 안내자라 AI 화면이 아니어도 나온다(DESIGN.md 「핑고」). 찾던 게 없거나 끊긴 곳은 sorry 다.
 */
export default function EmptyState({
  mood = 'default',
  title,
  children,
  action,
}: {
  mood?: PingoMood
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center py-6 text-center">
      <Pingo size={56} mood={mood} />
      <p className="mt-3 font-bold text-ink-900">{title}</p>
      <p className="mt-1 break-keep text-sm text-ink-500">{children}</p>
      {/* flex 로 감싸 링크(<a>)도 버튼처럼 블록으로 선다. */}
      {action && <div className="mt-4 flex">{action}</div>}
    </div>
  )
}
