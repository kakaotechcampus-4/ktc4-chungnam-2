import type { ReactNode } from 'react'
import { TriangleAlert } from 'lucide-react'

/**
 * 안내 상자 — 화면 위에서 "왜 이렇게 됐는지"와 다음 행동을 말한다(예: 원한 조건에 맞는 곳이 없어 다른 곳을 골랐다).
 * 연결 끊김 띠와 같은 세트: ink-100 면 + warn-line 아이콘 + ink-700 글자. 노랑 면은 확정 골드와 겹쳐서 쓰지 않는다(#299).
 */
export default function Notice({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div role="status" className="flex items-start gap-2 rounded-xl bg-ink-100 p-3 text-body text-ink-700">
      <TriangleAlert size={14} className="mt-0.5 shrink-0 text-[var(--warn-line)]" aria-hidden="true" />
      <div className="min-w-0 flex-1 space-y-2">
        <p>{children}</p>
        {action}
      </div>
    </div>
  )
}
