import type { ReactNode } from 'react'

import type { RecommendRunDto } from '@/features/recommend/model'
import { PingoMark } from '@/ui/Pingo'

import AdviceText from './AdviceText'
import { useRunAdviceQuery } from './queries'

/**
 * 추천 막힘 조언(agent-v2 9절, 16.5) — 결과가 적거나 같은 카테고리를 여러 번 받았을 때 더 받는 방법. 대상인지는 서버가 정한다.
 * 깔때기 아래에 둔다. 기다리는 동안 자리만 두고, 204·실패면 아무것도 없다.
 * 버튼은 둘뿐이다: widen_radius 는 화면의 「반경 넓히기」(확인 창 포함, 가드레일 4)를 그대로 받고, open_evidence 는 결과 위
 * 「이 조건으로 찾았어요」 카드를 연다(#849, `onOpenEvidence`). `widen` 을 주지 않으면(0곳 화면처럼 이미 같은 버튼이 있을 때) 문장만 보인다.
 */
export default function RunAdvice({ run, widen, onOpenEvidence }: { mapId: string; run: RecommendRunDto; widen?: ReactNode; onOpenEvidence?: () => void }) {
  const advice = useRunAdviceQuery(run.id)

  if (advice.isPending) return <div aria-hidden="true" className="h-16 rounded-xl bg-ink-50" />
  if (advice.error) {
    console.error('[agent] 추천 막힘 조언을 받지 못했어요', advice.error)
    return null
  }
  if (!advice.data) return null

  const actions = widen
    ? advice.data.actions.map((a) =>
        a.type === 'widen_radius' ? (
          <span key={a.index}>{widen}</span>
        ) : a.type === 'open_evidence' && onOpenEvidence ? (
          // ponytail: evidence_line_ids 강조는 아직 없다 — 조건 카드에 줄 강조가 생기면 넘긴다.
          <button key={a.index} type="button" onClick={onOpenEvidence} className="btn-outline btn-sm">
            {a.label}
          </button>
        ) : null,
      )
    : []

  return (
    <section aria-label="핑고 조언" className="space-y-2 rounded-xl bg-[var(--pingo-bg)] p-3">
      <p className="flex items-center gap-1.5 text-sm font-bold text-ink-900">
        <PingoMark size={20} />
        더 많이 추천받으려면
      </p>
      <ul className="space-y-1 text-body text-ink-900">
        {advice.data.advice.map((l, i) => (
          <li key={i} className="flex items-start gap-1.5">
            {l.is_guess && <span className="tag tag-neutral mt-px">추정</span>}
            <span className="min-w-0 break-keep">
              <AdviceText line={l} />
            </span>
          </li>
        ))}
      </ul>
      {actions.some(Boolean) && <div className="flex flex-wrap gap-2">{actions}</div>}
    </section>
  )
}
