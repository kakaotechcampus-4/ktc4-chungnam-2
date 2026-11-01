import type { Ref } from 'react'
import { X } from 'lucide-react'

/**
 * 한 줄 입력칸(.field 틀). 글자가 있을 때만 ✕ 와 글자 수가 보인다(Figma 입력칸 규칙).
 * 글자는 16px — 아이폰 Safari 는 16px 보다 작은 입력칸에 포커스하면 화면을 확대해 지도 화면이 어긋난다.
 */
export default function TextField({
  value,
  onChange,
  maxLength,
  placeholder,
  label,
  clearLabel,
  id,
  autoFocus,
  inputRef,
  describedBy,
}: {
  value: string
  onChange: (value: string) => void
  maxLength: number
  placeholder?: string
  /** 눈에 보이는 label 이 따로 없을 때의 이름. */
  label?: string
  clearLabel: string
  id?: string
  autoFocus?: boolean
  /** 안내·오류를 띄우고 입력칸으로 포커스를 보낼 때(#959). */
  inputRef?: Ref<HTMLInputElement>
  /** 입력칸 아래 안내·오류 글의 id. 있으면 그 글이 잘못된 입력이라는 뜻으로 함께 읽힌다. */
  describedBy?: string
}) {
  return (
    <div className="field">
      <input
        id={id}
        ref={inputRef}
        aria-describedby={describedBy}
        aria-invalid={describedBy ? true : undefined}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        maxLength={maxLength}
        autoFocus={autoFocus}
        placeholder={placeholder}
        aria-label={label}
        className="min-w-0 flex-1 bg-transparent outline-none placeholder:text-ink-500"
      />
      {value && <ClearButton label={clearLabel} onClick={() => onChange('')} />}
      {value && (
        <span className="shrink-0 text-label text-ink-500">
          {value.length}/{maxLength}
        </span>
      )}
    </div>
  )
}

/** 입력칸 안 ✕(지우기). 보이는 원은 20px, 누르는 영역은 44px. */
export function ClearButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="hit-44 flex size-5 shrink-0 items-center justify-center rounded-full bg-ink-500 text-white"
    >
      <X size={12} aria-hidden="true" />
    </button>
  )
}
