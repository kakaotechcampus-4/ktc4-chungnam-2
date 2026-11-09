import { useState } from 'react'
import { MessageSquare, Users } from 'lucide-react'

import type { MemberView } from '@/features/maps/model'
import Mark from '@/ui/Mark'

import { fulfillmentLine, memberConditions, sourceLabel, toChecks, type AiEvidence, type CheckView } from './model'

const TONE = { pass: 'tag-good', check: 'tag-warn', fail: 'tag-bad' } as const
const MARK = {
  pass: <Mark kind="check" size={12} />,
  check: <Mark kind="unknown" size={12} />,
  fail: <Mark kind="cross" size={12} />,
} as const

/**
 * AI가 고른 장소의 근거(가드레일 5) — 추천 이유, 조건별 충족 체크, 구성원 충족 집계, 출처.
 * 올리기 전 후보 카드와 지도에 올린 핀의 상세가 이 부품을 같이 쓴다(#1032). 올린 뒤에도 같은 값이 그대로 보인다.
 */
export function AiReason({ text }: { text: string }) {
  return (
    <p className="flex gap-2 rounded-xl border border-brand-300 bg-surface p-2.5 text-body text-ink-900">
      <MessageSquare size={14} className="mt-0.5 shrink-0 text-ink-500" aria-hidden="true" />
      {text}
    </p>
  )
}

export function AiChecks({ evidence }: { evidence: AiEvidence }) {
  const checks = toChecks(evidence)
  if (checks.length === 0) return null
  return <CheckTags checks={checks} />
}

function CheckTags({ checks }: { checks: CheckView[] }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {/* 같은 조건이 직접 쓴 줄과 ♥ 양쪽에서 와 라벨이 겹칠 수 있다. */}
      {checks.map((k, i) => (
        <li key={`${k.label}-${i}`} className={`tag ${TONE[k.tone]}`}>
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
      <p className="flex items-center gap-1.5 text-xs font-bold text-selected">
        {f && (
          <>
            <Users size={14} aria-hidden="true" /> {f.total}명 중 {f.satisfied}명이 조건에 맞아요
          </>
        )}
        <span className="ml-auto font-normal text-ink-600">출처: {sourceLabel(evidence)}</span>
      </p>
      {f && <p className="text-xs text-ink-600">{fulfillmentLine(evidence, members)}</p>}
      <MemberConditions evidence={evidence} members={members} />
    </>
  )
}

/**
 * 구성원마다 조건별 ✓·✗·확인 필요(#796). 구성원 수 × 조건 수만큼 태그가 늘어 카드가 길어지므로
 * 위 한 줄(「A 조건 2/3 충족」)만 늘 보이고 조건별 태그는 펼쳐서 본다. 구버전 서버(conditions 없음)면 아무것도 없다.
 */
function MemberConditions({ evidence, members }: { evidence: AiEvidence; members: MemberView[] }) {
  const [open, setOpen] = useState(false)
  const rows = memberConditions(evidence, members)
  if (!rows.length) return null
  return (
    <div className="space-y-2">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="btn-link text-xs">
        {open ? '구성원별 조건 접기' : '구성원별 조건 보기'}
      </button>
      {open && (
        <ul className="space-y-2" aria-label="구성원별 조건">
          {rows.map((m) => (
            <li key={m.userId} className="space-y-1">
              <p className="text-xs font-semibold text-ink-900">{m.name}</p>
              <CheckTags checks={m.checks} />
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
