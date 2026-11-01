import { ChevronDown } from 'lucide-react'

import ErrorText from '@/ErrorText'
import PingoLoading from '@/ui/PingoLoading'

import EvidenceGroups from './EvidenceGroups'
import type { EvidenceLineDto, RecommendRunDto } from './model'
import { useEvidenceQuery } from './queries'

/** 조건 줄(꼭·선호). 참고(원문 인용)는 조건이 아니다. */
const isCondition = (l: EvidenceLineDto) => l.is_active && l.badge !== 'reference'
/** 그중 이번 추천이 실제로 거르거나 순위에 쓴 줄 — 접힌 줄의 「조건 N개」는 이것만 센다(쓰이지 않는 줄은 펼치면 따로 보인다, #742). */
const isUsed = (l: EvidenceLineDto) => isCondition(l) && l.enforced !== false

/**
 * 「이 조건으로 찾았어요」(#849) — 결과 위 접힌 카드. 이번 결과에 실제 쓴 조건(applied_evidence 스냅숏)을 보여 주고,
 * 펼치면 그 자리에서 × ·＋ 로 고친다. 고친 것은 지금 결과에 안 쓰였으니 「아직 적용 전」으로 따로 보이고 「다시 추천」 때 반영된다.
 * 서버가 스냅숏을 안 주면(구버전) 지금 조건만 보인다. 고치기에는 횟수 상한이 없다(#432 D5).
 * 펼침은 부르는 쪽이 갖는다 — 0곳 화면의 「조건 고치기」, 조언의 근거 버튼도 이 카드를 연다.
 */
export default function ConditionsCard({
  run,
  applied,
  noApplied,
  open,
  onOpenChange,
}: {
  run: RecommendRunDto
  applied?: EvidenceLineDto[]
  noApplied?: boolean
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const evidence = useEvidenceQuery(run.id)
  const lines = evidence.data ?? []

  // 스냅숏과 지금 조건의 차이 = 고쳤지만 아직 결과에 안 쓰인 것. 스냅숏이 없으면 비교하지 않는다.
  const appliedIds = new Set((applied ?? []).filter(isCondition).map((l) => l.id))
  const pending = (l: EvidenceLineDto) => applied !== undefined && isCondition(l) && !appliedIds.has(l.id)
  const removed = applied === undefined ? [] : lines.filter((l) => !l.is_active && appliedIds.has(l.id))
  const changed = lines.filter(pending).length + removed.length
  const count = (applied ?? lines).filter(isUsed).length

  return (
    <section className="rounded-xl border border-ink-200 bg-white">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => onOpenChange(!open)}
        className="flex w-full items-start gap-2 p-3 text-left"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-bold text-ink-900">
            이 조건으로 찾았어요 · {noApplied ? '적용된 사유 조건이 없어요' : `조건 ${count}개`}
          </span>
          {/* 글은 꼭 필요한 한 줄만 — 고친 게 있을 때(2026-10-31). */}
          {changed > 0 && (
            <span className="mt-1 block text-xs font-bold text-[var(--warn-text)]">고친 조건 {changed}개 · 다시 추천 때 반영</span>
          )}
        </span>
        <ChevronDown
          size={20}
          aria-hidden="true"
          className={`shrink-0 text-ink-500 transition-transform duration-200 ease-out motion-reduce:transition-none ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="border-t border-ink-100 p-3">
          {evidence.isPending && <PingoLoading label="조건을 불러오는 중…" />}
          {evidence.error && <ErrorText message="조건을 불러오지 못했어요" error={evidence.error} />}
          {evidence.data && (
            <EvidenceGroups
              runId={run.id}
              lines={lines}
              pending={pending}
              removed={removed}
            />
          )}
        </div>
      )}
    </section>
  )
}
