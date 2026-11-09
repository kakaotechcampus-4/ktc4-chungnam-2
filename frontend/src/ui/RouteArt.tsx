/**
 * 코스 그림(#1713) — 접힌 지도 위 점선 길이 출발점에서 핀까지 이어진다. 핑고와 같은 결이다(평면, 둥근 선, 핑고 외곽선 색).
 * AI 코스 입력 화면의 최근 코스 카드 아이콘 자리에 쓴다. 이모지와 일반 아이콘 대신 서비스 그림을 쓰려고 그렸다.
 * 캐릭터 그림처럼 다크에서도 밝은 색 그대로다(`keep-light`).
 */
export default function RouteArt({ size = 40 }: { size?: number }) {
  const line = { stroke: 'var(--pingo-outline)', strokeWidth: 1.3, strokeLinejoin: 'round' } as const
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden="true" className="keep-light shrink-0">
      <rect width="40" height="40" rx="10" fill="var(--brand-50)" />
      {/* 세 쪽으로 접힌 지도. 가운데 쪽은 접힌 그늘로 한 단계 어둡다. */}
      <path d="M7 12L15 9V30L7 33Z" fill="white" {...line} />
      <path d="M15 9L25 12V33L15 30Z" fill="var(--ink-100)" {...line} />
      <path d="M25 12L33 9V30L25 33Z" fill="white" {...line} />
      {/* 출발점에서 핀까지 점선 길 */}
      <path d="M11 27C14 24 15 22 19 23C23 24 24 20 27 17" fill="none" stroke="var(--brand-600)" strokeWidth="1.8" strokeLinecap="round" strokeDasharray="0.1 3.2" />
      <circle cx="11" cy="27" r="2" fill="var(--brand-600)" stroke="white" strokeWidth="1" />
      {/* 도착 핀 — 핑고 머리 핀과 같은 모양 */}
      <path d="M28 17.5C25.6 15.3 24.5 13.8 24.5 12.3A3.5 3.5 0 0 1 31.5 12.3C31.5 13.8 30.4 15.3 28 17.5Z" fill="var(--pingo-body)" stroke="white" strokeWidth="1" />
      <circle cx="28" cy="12.3" r="1.3" fill="white" />
    </svg>
  )
}
