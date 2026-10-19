/** 불러오는 중(Figma '불러오는 중') — 글자 대신 카드 모양 자리를 먼저 보여 준다. 핀 목록·내 지도 목록이 쓴다. */
export default function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <ul className="space-y-2.5" aria-hidden="true">
      {Array.from({ length: count }, (_, i) => (
        <li key={i} className="animate-pulse space-y-2 rounded-xl border border-ink-200 bg-white p-3.5 motion-reduce:animate-none">
          <div className="h-4 w-2/3 rounded-sm bg-ink-100" />
          <div className="h-3 w-1/2 rounded-sm bg-ink-100" />
          <div className="h-3 w-1/3 rounded-sm bg-ink-100" />
        </li>
      ))}
    </ul>
  )
}
