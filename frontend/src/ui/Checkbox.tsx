import type { ReactNode } from 'react'

/**
 * 목록에서 여러 개 고르기(카톡 대화에서 가져오기 #578). 브라우저 체크박스에 행동 색만 입힌다 — 키보드·스크린리더는 그대로.
 * 보이는 상자는 20px이고, 옆 글자까지 줄 전체를 label로 감싸 누르는 곳을 높이 44px 이상으로 잡는다
 * (input에는 hit-44의 ::before가 그려지지 않는다). 이름은 옆 글자다.
 */
export default function Checkbox({
  checked,
  onChange,
  disabled,
  children,
}: {
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <label className="flex min-h-11 min-w-0 flex-1 cursor-pointer items-center gap-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        disabled={disabled}
        className="size-5 shrink-0 accent-[var(--action-fill)] disabled:opacity-50"
      />
      <span className="min-w-0 flex-1">{children}</span>
    </label>
  )
}
