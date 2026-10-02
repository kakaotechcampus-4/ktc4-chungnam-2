/** 핑고 — AI 쪽 화자(docs/design/colors.md 4절 3층). 그림 파일이 생기면 이 자리만 바꾼다. */
export default function Pingo({ size = 40 }: { size?: number }) {
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} aria-hidden="true">
      <path d="M20 4c8 0 14 7 14 17v13H6V21C6 11 12 4 20 4z" fill="var(--pingo-body)" />
      <circle cx="15" cy="20" r="2.2" fill="var(--ink-900)" />
      <circle cx="25" cy="20" r="2.2" fill="var(--ink-900)" />
      <path d="M17 26q3 2 6 0" stroke="var(--ink-900)" strokeWidth="1.6" fill="none" strokeLinecap="round" />
    </svg>
  )
}
