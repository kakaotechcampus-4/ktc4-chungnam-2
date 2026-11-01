import { Star } from 'lucide-react'

/** 별 개수. 별점은 1~5 정수다(docs/api-spec.yaml ReviewUpsertRequest.rating). */
export const STAR_COUNT = 5
const STARS = Array.from({ length: STAR_COUNT }, (_, i) => i + 1)

/**
 * 별점(#953). `onChange` 가 없으면 보기용(평균 4.3 같은 값은 가까운 별 수로 칠하고 숫자는 옆에 따로 적는다),
 * 있으면 고르기용(별 하나가 라디오 하나, 누르는 곳 44px). 켜진 별은 UI 파랑, 꺼진 별은 컨트롤 선 회색이다 —
 * 골드는 확정 전용이라 쓰지 않는다(DESIGN.md 색 영역). 별만으로 값을 전하지 않게 보기용은 읽는 글을 붙인다.
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
      className={n <= filled ? 'text-[var(--action-fill)]' : 'text-[var(--line-control)]'}
      fill={n <= filled ? 'currentColor' : 'none'}
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

  return (
    <div role="radiogroup" aria-label={label} className="flex items-center">
      {STARS.map((n) => (
        <button
          key={n}
          type="button"
          role="radio"
          aria-checked={n === value}
          aria-label={`${n}점`}
          onClick={() => onChange(n)}
          className="flex h-11 w-11 items-center justify-center"
        >
          {star(n)}
        </button>
      ))}
    </div>
  )
}
