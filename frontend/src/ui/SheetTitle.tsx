import type { ReactNode } from 'react'

/** 시트·모달의 제목(20/700). 탭 제목, 핀 이름, 검색 결과 머리, 확인 창 제목이 모두 이 크기다. */
export default function SheetTitle({ as: Tag = 'h2', children }: { as?: 'h1' | 'h2' | 'h3'; children: ReactNode }) {
  return <Tag className="truncate text-xl font-bold text-ink-900">{children}</Tag>
}
