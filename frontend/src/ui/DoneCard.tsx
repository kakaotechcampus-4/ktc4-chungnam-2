import type { ReactNode } from 'react'

import Sentences from './Sentences'

/** 완료 체크 — 초록 원이 커지며 나타나고 흰 체크가 그려진다(`done-check`, index.css). */
export function DoneCheck({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" className="done-check shrink-0">
      <circle cx="16" cy="16" r="16" fill="var(--good-line)" />
      <path d="M9.5 16.5l4.5 4.5 8.5-9" fill="none" stroke="white" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/**
 * 할 일을 다 끝냈을 때의 카드 — 좋음 초록 면 + 완료 체크 + 제목 + 다음 할 일 한 줄 + 다음 행동 버튼 하나.
 * 회색 글 한 줄로 두면 다 끝난 것이 눈에 띄지 않아서 만들었다. 끝나지 않은 일은 `TaskProgress`다.
 * `role="status"`라 바뀌는 순간 화면 읽기가 읽는다.
 */
export default function DoneCard({ title, children, action }: { title: string; children?: string; action?: ReactNode }) {
  return (
    <section role="status" className="flex items-center gap-3 rounded-xl bg-[var(--good-bg)] p-3.5">
      <DoneCheck />
      <div className="min-w-0 flex-1">
        <p className="break-keep text-sm font-bold text-ink-900">{title}</p>
        {children && (
          <p className="mt-0.5 break-keep text-xs text-ink-600">
            <Sentences text={children} />
          </p>
        )}
      </div>
      {action && <div className="flex shrink-0">{action}</div>}
    </section>
  )
}
