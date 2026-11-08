import type { ReactNode } from 'react'
import { DropdownMenu } from 'radix-ui'
import { Ellipsis } from 'lucide-react'

export type ActionMenuItem = {
  label: string
  onSelect: () => void
  /** 되돌리기 어려운 동작(지도 삭제)은 빨간 글자로 마지막에 둔다. */
  danger?: boolean
  icon?: ReactNode
}

/**
 * 카드 구석의 「⋯」 버튼이 여는 동작 메뉴(내 지도 카드, #1444). 화면 폭과 관계없이 버튼 바로 아래에 붙는다.
 * 고른 뒤 확인 창을 띄우는 동작이 많아서 메뉴는 고르는 즉시 닫힌다. 방향키·Esc·포커스 되돌리기는 radix DropdownMenu 가 맡는다.
 */
export default function ActionMenu({ label, items }: { label: string; items: ActionMenuItem[] }) {
  if (items.length === 0) return null
  return (
    <DropdownMenu.Root modal={false}>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label={label}
          className="hit-44 flex size-8 items-center justify-center rounded-full text-ink-600 hover:bg-ink-100 data-[state=open]:bg-ink-100"
        >
          <Ellipsis size={20} aria-hidden="true" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={4}
          collisionPadding={16}
          className="z-50 min-w-44 rounded-xl border border-ink-200 bg-surface p-1 shadow-float outline-none"
        >
          {items.map((item) => (
            <DropdownMenu.Item
              key={item.label}
              onSelect={item.onSelect}
              className={`flex h-11 cursor-pointer items-center gap-2 rounded-lg px-3 text-sm font-semibold outline-none data-[highlighted]:bg-ink-50 ${
                item.danger ? 'text-[var(--action-danger)]' : 'text-ink-900'
              }`}
            >
              {item.icon}
              {item.label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}
