import type { ReactNode } from 'react'

/**
 * 여러 후보 중 하나 고르기(카톡 가져오기의 이름 검색 후보 #1046). `Checkbox`와 같은 모양 — 브라우저 라디오에 행동 색만 입힌다.
 * 같은 `name`끼리 하나만 켜진다. 줄 전체가 label이라 누르는 곳이 높이 44px 이상이다. 이름은 옆 글자다.
 */
export default function Radio({
  name,
  checked,
  onChange,
  disabled,
  children,
}: {
  name: string
  checked: boolean
  onChange: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <label className="flex min-h-11 min-w-0 flex-1 cursor-pointer items-center gap-3">
      <input
        type="radio"
        name={name}
        checked={checked}
        onChange={onChange}
        disabled={disabled}
        className="size-5 shrink-0 accent-[var(--action-fill)] disabled:opacity-50"
      />
      <span className="min-w-0 flex-1">{children}</span>
    </label>
  )
}
