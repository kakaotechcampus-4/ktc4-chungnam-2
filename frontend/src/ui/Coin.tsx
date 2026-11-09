/**
 * 크레딧 동전(DESIGN.md 「크레딧 동전」). 테두리 · 금색 면 · 가운데 세로 홈 · 왼쪽 위 빛. 색은 `--coin-*` 토큰이다.
 * `CoinShape` 는 다른 그림(핑고가 든 동전) 안에 그대로 놓는 도형, `Coin` 은 글 옆에 놓는 16×16 기호다.
 */
export function CoinShape({ cx, cy, r }: { cx: number; cy: number; r: number }) {
  return (
    <g>
      <circle cx={cx} cy={cy} r={r} fill="var(--coin-rim)" />
      <circle cx={cx} cy={cy} r={r * 0.78} fill="var(--coin-face)" />
      <rect x={cx - r * 0.14} y={cy - r * 0.42} width={r * 0.28} height={r * 0.84} rx={r * 0.14} fill="var(--coin-rim)" />
      <path
        d={`M${cx - r * 0.5} ${cy - r * 0.1}A${r * 0.52} ${r * 0.52} 0 0 1 ${cx - r * 0.1} ${cy - r * 0.5}`}
        stroke="var(--coin-shine)"
        strokeWidth={r * 0.16}
        strokeLinecap="round"
        fill="none"
      />
    </g>
  )
}

export default function Coin({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="shrink-0">
      <CoinShape cx={8} cy={8} r={7.5} />
    </svg>
  )
}
