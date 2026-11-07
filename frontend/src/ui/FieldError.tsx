import type { ReactNode } from 'react'
import { CircleAlert } from 'lucide-react'

/**
 * 입력칸 바로 아래의 입력 오류 한 줄(#1447). 칸이 aria-describedby 로 이 id 를 가리킨다.
 * 색은 주의색(--warn-*)이다 — 빨강은 핀·반대·되돌릴 수 없는 동작 전용(docs/design/colors.md 6절).
 * 색만으로 알리지 않게 경고 기호와 굵은 14px 글자를 함께 쓴다.
 */
export default function FieldError({ id, children, className = '' }: { id: string; children: ReactNode; className?: string }) {
  return (
    <p id={id} className={`flex items-start gap-1.5 text-sm font-semibold text-[var(--warn-text)] ${className}`}>
      <CircleAlert size={16} className="mt-0.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </p>
  )
}
