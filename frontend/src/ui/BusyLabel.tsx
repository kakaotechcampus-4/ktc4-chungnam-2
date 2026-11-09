import type { ReactNode } from 'react'
import { Check, Loader2 } from 'lucide-react'

/**
 * 버튼 안의 기다림 표시(#1668, 버튼 상태 「로딩」). 기다리는 동안 도는 아이콘 + 「저장하는 중…」, 아니면 원래 글자.
 * 글자만 바뀌면 눌렸는지 한눈에 알기 어려웠다. 버튼 크기 클래스(`btn-lg`·`md`·`sm`)가 이미 아이콘과 글자를 나란히 놓는다.
 * 버튼에는 부르는 쪽이 `disabled`와 `aria-busy`를 단다. 동작 줄이기면 돌지 않는다.
 * `done`이면 끝난 표시(#1712, 버튼 상태 "성공"): 체크가 그려지며 doneText. 버튼 면을 초록으로 바꾸는 것은 `btn-done`(index.css)이다.
 */
export default function BusyLabel({
  busy,
  busyText,
  done = false,
  doneText,
  children,
}: {
  busy: boolean
  busyText: string
  done?: boolean
  doneText?: string
  children: ReactNode
}) {
  if (done) {
    return (
      <>
        <Check size={18} strokeWidth={3} aria-hidden="true" className="done-check shrink-0" />
        {doneText}
      </>
    )
  }
  if (!busy) return <>{children}</>
  return (
    <>
      <Loader2 size={16} aria-hidden="true" className="shrink-0 animate-spin motion-reduce:animate-none" />
      {busyText}
    </>
  )
}
