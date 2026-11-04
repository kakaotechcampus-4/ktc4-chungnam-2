import { useState } from 'react'
import { ArrowRight, Check } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'

import { applyFix } from './applyFix'
import { useAppliedFixStore } from './courseMapStore'
import { checkedOf, dayOrdinal, fixesOf, hasMoves, isFill, sortFixes, stalePrompt, type CourseFixDto, type CourseRunDto } from './model'

/**
 * 고칠 점 카드와 「괜찮아요」(#1322, 결정 #1237). 문장은 모두 서버가 만든 것을 그대로 보인다.
 * 「반영」은 카드마다 사람이 누른다 — 서버에 반영 API가 없어 지금 일정을 읽어 moves대로 옮기고 일정 API로 저장한다.
 */
export default function FixCards({ mapId, run, names }: { mapId: string; run: CourseRunDto; names: Map<string, string> }) {
  const fixes = sortFixes(fixesOf(run))
  const checked = checkedOf(run)
  // 날짜 → 「첫째 날」. 지도의 날짜 순서는 run.days 와 같다.
  const dayName = (date: string | null) => {
    if (!date) return '미배정'
    const i = run.days.findIndex((d) => d.date === date)
    return i === -1 ? date : dayOrdinal(i)
  }
  return (
    <div className="space-y-3">
      {fixes.length > 0 && (
        <ul aria-label="고칠 점" className="space-y-2">
          {fixes.map((fix) => (
            <li key={fix.id}>
              <FixCard mapId={mapId} runId={run.id} fix={fix} names={names} dayName={dayName} />
            </li>
          ))}
        </ul>
      )}
      {checked.length > 0 && (
        <section aria-label="괜찮아요" className="rounded-xl bg-[var(--good-bg)] p-3">
          <h3 className="text-sm font-bold text-[var(--good-text)]">괜찮아요</h3>
          <ul className="mt-1 space-y-0.5">
            {checked.map((c, i) => (
              <li key={`${c.kind}-${i}`} className="break-keep text-body text-[var(--good-text)]">
                · {c.text}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}

function FixCard({
  mapId,
  runId,
  fix,
  names,
  dayName,
}: {
  mapId: string
  runId: string
  fix: CourseFixDto
  names: Map<string, string>
  dayName: (date: string | null) => string
}) {
  const queryClient = useQueryClient()
  const applied = useAppliedFixStore((s) => s.applied[runId]?.includes(fix.id) ?? false)
  const mark = useAppliedFixStore((s) => s.mark)
  const [state, setState] = useState<{ pending: boolean; error: unknown }>({
    pending: false,
    error: null,
  })
  const stale = state.error instanceof ApiError && state.error.code === 'SHORTLIST_STALE'
  const movable = hasMoves(fix)
  const fill = movable && isFill(fix)

  async function apply() {
    setState({ pending: true, error: null })
    try {
      await applyFix(queryClient, mapId, fix.moves)
      mark(runId, fix.id)
      setState({ pending: false, error: null })
    } catch (error) {
      setState({ pending: false, error })
    }
  }

  return (
    <article className={`space-y-2 rounded-xl bg-white p-3 ring-1 ring-ink-200 ${fix.strength === 'hard' ? 'border-l-4 border-[var(--warn-line)]' : ''}`}>
      <span className={`tag ${fix.strength === 'hard' ? 'tag-warn' : 'tag-neutral'}`}>{fix.strength === 'hard' ? '꼭 고칠 것' : '선호'}</span>
      <h3 className="break-keep text-base font-bold text-ink-900">{fix.text}</h3>

      {movable ? (
        <>
          <ul className="space-y-1 rounded-lg bg-ink-50 p-2 text-body text-ink-700">
            {fix.moves.map((m) => (
              <li key={m.pin_id} className="flex flex-wrap items-center gap-x-1">
                <span className="font-semibold text-ink-900">{names.get(m.pin_id) ?? '이 장소'}</span>:<span>{dayName(m.from_date)}</span>
                <ArrowRight size={12} aria-hidden="true" />
                <span>{dayName(m.to_date)}</span>
              </li>
            ))}
          </ul>
          {fix.resolved_text && (
            <p className="flex items-start gap-1 break-keep text-body text-[var(--good-text)]">
              <Check size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
              {fix.resolved_text}
            </p>
          )}
          {fix.remaining_text && <p className="break-keep text-body text-ink-700">{fix.remaining_text}</p>}
          {applied ? (
            <p className="flex items-center gap-1 text-body font-semibold text-[var(--good-text)]">
              <Check size={14} aria-hidden="true" /> 반영했어요
            </p>
          ) : (
            <button type="button" onClick={() => void apply()} disabled={state.pending} className="btn-primary btn-md">
              {state.pending ? '반영하는 중…' : fill ? `${dayName(fix.moves[0].to_date)}에 넣기` : '반영'}
            </button>
          )}
          {stale && (
            <p role="alert" className="break-keep text-body text-warn-text">
              {stalePrompt}. 다시 점검해 주세요
            </p>
          )}
          {state.error != null && !stale && <ErrorText message="일정에 반영하지 못했어요" error={state.error} />}
        </>
      ) : (
        // 고치지 않기로 한 카드 — 이유만 보이고 「반영」은 없다.
        fix.not_fixed_reason && <p className="break-keep text-body text-ink-700">{fix.not_fixed_reason}</p>
      )}
    </article>
  )
}
