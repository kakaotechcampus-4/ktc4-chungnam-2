import { ClearButton } from './TextField'

/**
 * 여러 줄 입력칸(.field 틀). 한 줄 입력칸(`TextField`)과 같이 글자가 있을 때만 오른쪽 위에 ✕가 보인다.
 * `maxLength`가 있으면 칸 아래 오른쪽에 글자 수를 적는다. 글자는 16px(아이폰 확대 방지, TextField와 같은 이유).
 */
export default function TextArea({
  value,
  onChange,
  clearLabel,
  rows,
  maxLength,
  placeholder,
  label,
  id,
  className = '',
}: {
  value: string
  onChange: (value: string) => void
  clearLabel: string
  rows: number
  maxLength?: number
  placeholder?: string
  /** 눈에 보이는 label 이 따로 없을 때의 이름. */
  label?: string
  id?: string
  /** 바깥 여백(mt-3 등). */
  className?: string
}) {
  return (
    <div className={className}>
      <div className="field items-start py-3">
        <textarea
          id={id}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          maxLength={maxLength}
          rows={rows}
          placeholder={placeholder}
          aria-label={label}
          className="min-w-0 flex-1 resize-none bg-transparent outline-none placeholder:text-ink-500"
        />
        {value && <ClearButton label={clearLabel} onClick={() => onChange('')} />}
      </div>
      {maxLength !== undefined && (
        <p className="mt-1 text-right text-label text-ink-500">
          {value.length}/{maxLength}
        </p>
      )}
    </div>
  )
}
