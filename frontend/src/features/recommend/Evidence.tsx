import { useId, useState } from 'react'
import { Users } from 'lucide-react'

import type { MemberView } from '@/features/maps/model'
import Mark from '@/ui/Mark'
import { ProgressTrack } from '@/ui/ProgressBar'

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
/** 추천 이유 한 줄. 상자로 감싸지 않는다 — 카드 안 상자 안 상자가 글을 더 무겁게 보이게 했다(#1706). */
export function AiReason({ text }: { text: string }) {
  return <p className="break-keep text-body text-ink-900">{text}</p>
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

/**
 * 구성원 충족 한 줄(#1706) — "1명 중 1명이 조건에 맞아요" + 비율 막대 + "누가". 누가 통과했는지와 구성원별 조건은 "누가"를 눌러 본다.
 * 출처는 `withSource`면 이 줄 아래에 적는다. 후보 카드는 이름 아래 한 줄(`AiSource`)에 따로 적는다.
 */
export function AiFulfillment({ evidence, members, withSource = true }: { evidence: AiEvidence; members: MemberView[]; withSource?: boolean }) {
  const f = evidence.member_fulfillment
  const [open, setOpen] = useState(false)
  const labelId = useId()
  return (
    <>
      {f && (
        <div className="flex items-center gap-2 text-xs">
          <Users size={14} className="shrink-0 text-ink-600" aria-hidden="true" />
          <span id={labelId} className="shrink-0 text-ink-700">
            <b className="text-ink-900">
              {f.total}명 중 {f.satisfied}명
            </b>
            이 조건에 맞아요
          </span>
          <span className="min-w-0 flex-1">
            <ProgressTrack value={f.satisfied} max={f.total} labelledBy={labelId} quiet />
          </span>
          <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="btn-link shrink-0 text-xs">
            누가 {open ? <Mark kind="chevronUp" size={12} /> : <Mark kind="chevronDown" size={12} />}
          </button>
        </div>
      )}
      {f && open && (
        <div className="space-y-2">
          <p className="text-xs text-ink-600">{fulfillmentLine(evidence, members)}</p>
          <MemberConditions evidence={evidence} members={members} />
        </div>
      )}
      {withSource && <AiSource evidence={evidence} />}
    </>
  )
}

/** 출처(가드레일 5). 어느 데이터에서 온 장소인지. */
export function AiSource({ evidence, className = '' }: { evidence: AiEvidence; className?: string }) {
  return <p className={`text-xs text-ink-500 ${className}`}>출처: {sourceLabel(evidence)}</p>
}

/**
 * 구성원마다 조건별 ✓·✗·확인 필요(#796). 구성원 수 × 조건 수만큼 태그가 늘어 카드가 길어지므로
 * "누가"를 펼쳤을 때만 보인다(#1706). 구버전 서버(conditions 없음)면 아무것도 없다.
 */
function MemberConditions({ evidence, members }: { evidence: AiEvidence; members: MemberView[] }) {
  const rows = memberConditions(evidence, members)
  if (!rows.length) return null
  return (
    <ul className="space-y-2" aria-label="구성원별 조건">
      {rows.map((m) => (
        <li key={m.userId} className="space-y-1">
          <p className="text-xs font-semibold text-ink-900">{m.name}</p>
          <CheckTags checks={m.checks} />
        </li>
      ))}
    </ul>
  )
}
