import { timeAgo } from './model'

/**
 * 「마킹된 장소」 맨 위 — 마지막으로 본 뒤 새로 생긴 핀·의견을 모아 알린다(#1454, Troupe 「누가 무엇을 냈는지」).
 * 할 일·새 소식은 브랜드 파랑이다(DESIGN.md 「파랑은 할 일 규칙」). 「확인」을 누르면 카드 줄과 지도 점이 함께 사라진다.
 */
export default function NewSinceBanner({
  since,
  newPins,
  newOpinions,
  truncated = false,
  onDismiss,
}: {
  since: string
  newPins: number
  newOpinions: number
  /** 서버가 목록을 100개에서 잘랐다(#1556) — 지도에서 더 보라고 한 줄 더한다. */
  truncated?: boolean
  onDismiss: () => void
}) {
  if (!newPins && !newOpinions) return null
  const what = [newPins > 0 && `새 핀 ${newPins}곳`, newOpinions > 0 && `새 의견 ${newOpinions}개`].filter(Boolean).join(' · ')
  return (
    <div role="status" className="mb-2.5 flex items-start gap-2 rounded-xl border border-brand-300 bg-brand-50 p-3">
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold text-selected">{timeAgo(since)}에 본 뒤로 새로 생겼어요</p>
        <p className="mt-0.5 text-xs text-ink-600">{what}</p>
        <p className="text-xs text-ink-600">지도에 파란 점이 찍힌 핀이에요</p>
        {truncated && <p className="text-xs text-ink-600">새 소식이 더 있어요. 지도를 둘러봐 주세요</p>}
      </div>
      <button type="button" onClick={onDismiss} className="btn-text shrink-0 text-sm">
        확인
      </button>
    </div>
  )
}
