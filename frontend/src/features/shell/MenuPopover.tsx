import type { ReactNode } from 'react'
import { Popover } from 'radix-ui'

/**
 * 넓은 화면에서 모바일 바닥 시트(ModalSheet) 대신 쓰는, 누른 버튼 바로 아래에 붙는 메뉴(계정·지도 정보).
 * 딤이 없고, 바깥을 누르거나 Esc 로 닫는다. 토스트는 화면 쪽 토스트 자리에 뜬다.
 * `holdOpen` 이 켜져 있는 동안(확인 창이 떠 있을 때)은 닫지 않는다 — 모바일 시트 위에 확인 창이 뜨는 것과 같게,
 * 취소하면 메뉴로 돌아온다. 확인 창은 `overlay` 로 넘긴다.
 */
export default function MenuPopover({
  label,
  trigger,
  holdOpen = false,
  overlay,
  children,
}: {
  label: string
  /** 메뉴를 여는 버튼. ref 와 속성을 받아야 해서 <button> 그대로 넘긴다. */
  trigger: ReactNode
  holdOpen?: boolean
  overlay?: ReactNode
  children: ReactNode
}) {
  const keepOpen = (e: Event) => {
    if (holdOpen) e.preventDefault()
  }
  return (
    <Popover.Root>
      <Popover.Trigger asChild>{trigger}</Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          aria-label={label}
          align="end"
          sideOffset={8}
          collisionPadding={16}
          onInteractOutside={keepOpen}
          onFocusOutside={keepOpen}
          className="z-50 max-h-[var(--radix-popover-content-available-height)] w-[22rem] overflow-y-auto rounded-2xl border border-ink-200 bg-white p-4 shadow-float outline-none"
        >
          {children}
        </Popover.Content>
      </Popover.Portal>
      {overlay}
    </Popover.Root>
  )
}
