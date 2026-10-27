/** 로그인·초대 화면의 작은 지도 그림(Figma 1·2절). 실제 지도가 아니라 장식이라 스크린 리더에서 숨긴다. */
const PIN = 'M12 2C7.6 2 4 5.6 4 10c0 6 8 20 8 20s8-14 8-20c0-4.4-3.6-8-8-8z'

export default function MapIllustration({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 320 140" className={`w-full ${className}`} aria-hidden="true">
      <rect width="320" height="140" rx="12" fill="var(--ink-100)" />
      <path d="M0 98 L320 52 L320 66 L0 112 Z" fill="#fff" />
      <rect x="196" y="0" width="12" height="140" fill="#fff" />
      <g transform="translate(70 30)"><path d={PIN} fill="var(--pin-fill-full)" stroke="var(--pin-stroke)" strokeWidth="2.5" /></g>
      {/* AI 추천 핀 — 점선 + 회색 속(DESIGN.md 지도 핀). */}
      <g transform="translate(112 52)"><path d={PIN} fill="var(--pin-fill-empty)" stroke="var(--pin-stroke)" strokeWidth="2.5" strokeDasharray="4 3" /></g>
      {/* 참여율 절반 — 지도 핀과 같은 oklch 섞기. */}
      <g transform="translate(250 40)"><path d={PIN} style={{ fill: 'color-mix(in oklch, var(--pin-fill-full) 50%, var(--pin-fill-empty))' }} stroke="var(--pin-stroke)" strokeWidth="2.5" /></g>
    </svg>
  )
}
