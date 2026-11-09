/**
 * 크레딧 동전(DESIGN.md 「크레딧 동전」). 테두리 · 금색 면 · 가운데 세로 홈 · 왼쪽 위 빛. 색은 `--coin-*` 토큰이다.
 * 글 옆에 놓는 16×16 기호다.
 */
export default function Coin({ size = 16 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 16 16" aria-hidden="true" className="shrink-0">
      <circle cx="8" cy="8" r="7.5" fill="var(--coin-rim)" />
      <circle cx="8" cy="8" r="5.85" fill="var(--coin-face)" />
      <rect x="6.95" y="4.85" width="2.1" height="6.3" rx="1.05" fill="var(--coin-rim)" />
      <path d="M4.25 7.25A3.9 3.9 0 0 1 7.25 4.25" stroke="var(--coin-shine)" strokeWidth="1.2" strokeLinecap="round" fill="none" />
    </svg>
  )
}
