import { Star } from 'lucide-react'

/** 별 개수. 별점은 1~5 정수다(docs/api-spec.yaml ReviewUpsertRequest.rating). */
export const STAR_COUNT = 5
const STARS = Array.from({ length: STAR_COUNT }, (_, i) => i + 1)

/**
 * 별점(#953). `onChange` 가 없으면 보기용(평균 4.3 같은 값은 가까운 별 수로 칠하고 숫자는 옆에 따로 적는다),
 * 있으면 고르기용(별 하나가 라디오 하나, 누르는 곳 44px). 켜진 별은 별점 노랑 면 + 앰버 선(`--rating-star`, #1701), 꺼진 별은 컨트롤 선 회색이다.
 * 확정 골드 값은 쓰지 않는다 — 별점 전용 토큰이다. 별만으로 값을 전하지 않게 보기용은 읽는 글을, 고르기용은 고른 점수의 말을 붙인다.
 */
export default function StarRating({
  value,
  onChange,
  size = 12,
  label = '별점',
}: {
  value: number | null
  onChange?: (value: number) => void
  size?: number
  /** 고르기용 묶음의 이름. */
  label?: string
}) {
  const filled = Math.round(value ?? 0)
  const star = (n: number) => (
    <Star
      size={size}
      aria-hidden="true"
      className={n <= filled ? 'text-[var(--rating-star-line)]' : 'text-[var(--line-control)]'}
      fill={n <= filled ? 'var(--rating-star)' : 'none'}
    />
  )

  if (!onChange) {
    return (
      <span role="img" aria-label={value === null ? '별점 없음' : `별점 ${STAR_COUNT}점 만점에 ${value}점`} className="inline-flex items-center gap-px">
        {STARS.map((n) => (
          <span key={n}>{star(n)}</span>
        ))}
      </span>
    )
  }

  // 라디오 묶음 키보드 규칙: Tab은 고른 별(없으면 첫 별)에만 멈추고, ←→↑↓로 값을 바꾼다.
  const move = (e: React.KeyboardEvent<HTMLButtonElement>, n: number) => {
    const delta = e.key === 'ArrowRight' || e.key === 'ArrowUp' ? 1 : e.key === 'ArrowLeft' || e.key === 'ArrowDown' ? -1 : 0
    if (!delta) return
    e.preventDefault()
    const next = Math.min(STAR_COUNT, Math.max(1, n + delta))
    onChange(next)
    ;(e.currentTarget.parentElement?.children[next - 1] as HTMLElement | undefined)?.focus()
  }
  return (
    <div role="radiogroup" aria-label={label} className="flex items-center">
      {STARS.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={n === value}
          aria-label={`${n}점`}
          tabIndex={n === (value ?? 1) ? 0 : -1}
          onClick={() => onChange(n)}
          onKeyDown={(e) => move(e, n)}
          className="flex h-11 w-11 items-center justify-center"
        >
          {star(n)}
        </button>
      ))}
    </div>
  )
}
