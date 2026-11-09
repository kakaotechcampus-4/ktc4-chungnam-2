import type { ReactNode } from 'react'
import { Accordion as Radix } from 'radix-ui'
import { ChevronDown } from 'lucide-react'

/** `icon`은 `menu`에서만 — ☰ 메뉴 글자 줄(`MenuRow`)처럼 20 선 아이콘을 제목 앞에 둔다. 펼친 내용은 제목 글자와 줄을 맞춘다. */
export type AccordionItem = { id: string; title: ReactNode; body: ReactNode; icon?: ReactNode }

/**
 * 눌러서 펼쳐 보는 목록(자주 묻는 질문, ☰ 메뉴의 「설정」). 여러 개를 함께 펼칠 수 있다.
 * - `list`: 줄마다 아래 선, 제목 16/600 + 오른쪽 끝 ⌄. 높이 52 이상.
 * - `menu`: 선 없이 제목 바로 옆 ⌄(☰ 메뉴 글자 줄과 같은 크기). 펼친 내용은 제목 아래에 붙는다.
 * 제목 줄이 버튼이고 `aria-expanded`가 붙는다(Radix). 펼치면 ⌄가 뒤집힌다.
 */
export default function Accordion({ items, variant = 'list' }: { items: AccordionItem[]; variant?: 'list' | 'menu' }) {
  const list = variant === 'list'
  return (
    <Radix.Root type="multiple">
      {items.map((item) => (
        <Radix.Item key={item.id} value={item.id} className={list ? 'border-b border-ink-200' : ''}>
          <Radix.Header>
            <Radix.Trigger
              className={`group flex w-full items-center gap-1 text-left text-ink-900 ${
                list ? 'min-h-13 justify-between py-3 text-base font-semibold' : 'min-h-11 text-base font-medium hover:text-brand-600'
              }`}
            >
              {!list && item.icon && <span className="mr-2 text-ink-600">{item.icon}</span>}
              {item.title}
              <ChevronDown
                size={list ? 20 : 16}
                aria-hidden="true"
                className="shrink-0 text-ink-500 transition-transform group-data-[state=open]:rotate-180 motion-reduce:transition-none"
              />
            </Radix.Trigger>
          </Radix.Header>
          <Radix.Content className={list ? 'pb-4 text-sm text-ink-600' : `pb-2 ${item.icon ? 'pl-8' : ''}`}>{item.body}</Radix.Content>
        </Radix.Item>
      ))}
    </Radix.Root>
  )
}
