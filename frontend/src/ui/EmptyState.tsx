import type { ReactNode } from 'react'
import type { LucideIcon } from 'lucide-react'

/**
 * 비어 있을 때(빈 지도·필터 0곳·확정 0곳·지도 0개·끊긴 초대). 아이콘 + 제목 + 설명 + 다음 행동 하나(#359).
 * 핑고는 AI가 말하는 자리에만 나온다(DESIGN.md) — 여기는 AI 화면이 아니라서 회색 면 아이콘이다.
 */
export default function EmptyState({
  icon: Icon,
  title,
  children,
  action,
}: {
  icon: LucideIcon
  title: string
  children: ReactNode
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center py-6 text-center">
      <span className="flex size-14 items-center justify-center rounded-xl bg-ink-100 text-ink-500">
        <Icon size={28} aria-hidden="true" />
      </span>
      <p className="mt-3 font-bold text-ink-900">{title}</p>
      <p className="mt-1 break-keep text-sm text-ink-500">{children}</p>
      {/* flex 로 감싸 링크(<a>)도 버튼처럼 블록으로 선다. */}
      {action && <div className="mt-4 flex">{action}</div>}
    </div>
  )
}
