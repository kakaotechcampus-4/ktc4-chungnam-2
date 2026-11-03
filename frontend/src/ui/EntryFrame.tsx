import type { FormEventHandler, ReactNode } from 'react'

/**
 * 입구 화면 틀 — 좁은 화면은 화면을 꽉 채운 세로 띠(최대 480px), 768px 이상은 종이(ink-50) 바탕 가운데 400px 흰 카드다(#602, #1269).
 * 로그인·계정 복구·새 지도·초대 받기가 같이 쓴다.
 * `className`은 좁은 화면의 바탕과 안쪽 여백이다(화면마다 다르다). 카드 값(md:)이 뒤에 붙어 넓은 화면에서는 카드 모양이 이긴다.
 * 로그인처럼 `lg:` 값을 넘기면 그 값이 다시 덮는다. `after`는 카드 밖(같은 바탕 안)에 둘 것 — 확인 창·시트.
 */
export default function EntryFrame({
  as: Tag = 'main',
  className = '',
  onSubmit,
  after,
  children,
}: {
  as?: 'main' | 'form' | 'div'
  className?: string
  onSubmit?: FormEventHandler<HTMLFormElement>
  after?: ReactNode
  children: ReactNode
}) {
  const frame = `mx-auto flex min-h-dvh w-full max-w-[480px] flex-col ${className} md:mx-0 md:min-h-0 md:max-w-[400px] md:rounded-2xl md:border md:border-ink-200 md:bg-white md:px-8 md:py-10`
  return (
    <div className="min-h-dvh md:flex md:items-center md:justify-center md:bg-ink-50 md:px-5 md:py-10">
      {Tag === 'form' ? (
        <form onSubmit={onSubmit} className={frame}>
          {children}
        </form>
      ) : (
        <Tag className={frame}>{children}</Tag>
      )}
      {after}
    </div>
  )
}
