import { MessageSquare, Users } from 'lucide-react'

import type { MemberView } from '@/features/maps/model'

import { fulfillmentLine, sourceLabel, toChecks, type AiEvidence } from './model'

const TONE = { pass: 'tag-good', check: 'tag-warn', fail: 'tag-bad' } as const
const MARK = { pass: '✓', check: '?', fail: '✗' } as const

/**
 * AI가 고른 장소의 근거(가드레일 5) — 추천 이유, 조건별 충족 체크, 구성원 충족 집계, 출처.
 * 올리기 전 후보 카드와 지도에 올린 핀의 상세가 이 부품을 같이 쓴다(#1032). 올린 뒤에도 같은 값이 그대로 보인다.
 */
export function AiReason({ text }: { text: string }) {
  return (
    <p className="flex gap-2 rounded-xl border border-brand-300 bg-white p-2.5 text-body text-ink-900">
      <MessageSquare size={14} className="mt-0.5 shrink-0 text-ink-500" aria-hidden="true" />
      {text}
    </p>
  )
}

export function AiChecks({ evidence }: { evidence: AiEvidence }) {
  const checks = toChecks(evidence)
  if (checks.length === 0) return null
  return (
    <ul className="flex flex-wrap gap-1.5">
      {checks.map((k) => (
        <li key={k.label} className={`tag ${TONE[k.tone]}`}>
          {MARK[k.tone]} {k.label}
          {/* 라벨에 이미 「확인」이 들어 있으면 겹쳐 쓰지 않는다(「가격대 확인 필요 (확인 필요)」, #406). */}
          {k.tone === 'check' && !k.label.includes('확인') && ' (확인 필요)'}
        </li>
      ))}
    </ul>
  )
}

/** 구성원 충족 집계 한 줄 + 출처, 그 아래 누가 통과했는지 한 줄. */
export function AiFulfillment({ evidence, members }: { evidence: AiEvidence; members: MemberView[] }) {
  const f = evidence.member_fulfillment
  return (
    <>
      <p className="flex items-center gap-1.5 text-xs font-bold text-brand-700">
        {f && (
          <>
            <Users size={14} aria-hidden="true" /> {f.total}명 중 {f.satisfied}명 조건 충족
          </>
        )}
        <span className="ml-auto font-normal text-ink-600">출처 · {sourceLabel(evidence)}</span>
      </p>
      {f && <p className="text-xs text-ink-600">{fulfillmentLine(evidence, members)}</p>}
    </>
  )
}
