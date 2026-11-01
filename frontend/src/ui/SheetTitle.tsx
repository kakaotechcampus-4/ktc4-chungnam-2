import { useEffect, useRef, type ReactNode } from 'react'

/**
 * 시트·모달의 제목(20/700). 탭 제목, 핀 이름, 검색 결과 머리, 확인 창 제목이 모두 이 크기다.
 * 글자를 150%로 키워도 핀 이름이 잘리지 않게 두 줄까지 보인다(#406).
 *
 * 시트 내용이 바뀌며 누른 버튼이 사라지면 포커스가 갈 곳을 잃는다(VoiceOver는 화면 맨 위로, Tab은 처음부터).
 * 그래서 새로 그려진 제목이 포커스를 받는다(#959). 포커스가 아직 어딘가에 있으면(탭 버튼·입력칸) 뺏지 않고,
 * 페이지를 막 열어 아직 아무것도 누르지 않았을 때도 옮기지 않는다.
 */
export default function SheetTitle({ as: Tag = 'h2', children }: { as?: 'h1' | 'h2' | 'h3'; children: ReactNode }) {
  const ref = useRef<HTMLHeadingElement>(null)
  useEffect(() => {
    const lost = !document.activeElement || document.activeElement === document.body
    if (lost && (navigator.userActivation?.hasBeenActive ?? true)) ref.current?.focus({ preventScroll: true })
  }, [])
  return (
    <Tag ref={ref} tabIndex={-1} className="line-clamp-2 min-w-0 break-keep text-xl font-bold text-ink-900 focus:outline-none">
      {children}
    </Tag>
  )
}
