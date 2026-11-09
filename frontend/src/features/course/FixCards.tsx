import { useState } from 'react'
import { ArrowRight, Check } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'

import { applyFix } from './applyFix'
import { useAppliedFixStore } from './courseMapStore'
import { checkedOf, dayOrdinal, fixesOf, hasMoves, isFill, sortFixes, staleFixText, type CourseFixDto, type CourseRunDto } from './model'

/**
 * 고칠 점 카드와 「괜찮아요」(#1322, 결정 #1237). 문장은 모두 서버가 만든 것을 그대로 보인다.
 * 「반영」은 카드마다 사람이 누른다 — 서버에 반영 API가 없어 지금 일정을 읽어 moves대로 옮기고 일정 API로 저장한다.
 */
export default function FixCards({ mapId, run, names, onRetry }: { mapId: string; run: CourseRunDto; names: Map<string, string>; onRetry: () => void }) {
  const fixes = sortFixes(fixesOf(run))
  const checked = checkedOf(run)
  const queryClient = useQueryClient()
  const applied = useAppliedFixStore((s) => s.applied[run.id])
  const mark = useAppliedFixStore((s) => s.mark)
  const [bulk, setBulk] = useState<{ pending: boolean; error: unknown }>({ pending: false, error: null })
  // 「남은 곳 한 번에 넣기」(#1393) — 아직 반영하지 않은 미배정 카드들의 moves 를 모아 한 번에 저장한다. 미배정 장소는 카드끼리 겹치지 않아 그대로 넣어도 같은 결과다.
  // 카드를 하나라도 반영했거나 run 이 stale 이면 카드와 같은 잠금 규칙(#1377)으로 버튼을 없애고, 카드의 「다시 점검」이 그 자리를 맡는다.
  const rest = fixes.filter((f) => f.kind === 'unassigned' && hasMoves(f) && !(applied?.includes(f.id) ?? false))
  const restMoves = rest.flatMap((f) => f.moves)
  const bulkStale = bulk.error instanceof ApiError && bulk.error.code === 'SHORTLIST_STALE'
  const locked = run.stale || (applied?.length ?? 0) > 0 || bulkStale
  async function applyRest() {
    setBulk({ pending: true, error: null })
    try {
      // false 면 run 이 stale 로 바뀌어 캐시에 들어갔다 — 버튼이 사라지고 카드가 「다시 점검」으로 바뀐다.
      if (await applyFix(queryClient, mapId, run.id, restMoves)) for (const f of rest) mark(run.id, f.id)
      setBulk({ pending: false, error: null })
    } catch (error) {
      setBulk({ pending: false, error })
    }
  }
  // 날짜 → 「첫째 날」. 지도의 날짜 순서는 run.days 와 같다.
  const dayName = (date: string | null) => {
    if (!date) return '미배정'
    const i = run.days.findIndex((d) => d.date === date)
    return i === -1 ? date : dayOrdinal(i)
  }
  return (
    <div className="space-y-3">
      {rest.length > 1 && !locked && (
        <div className="space-y-2">
          <button type="button" onClick={() => void applyRest()} disabled={bulk.pending} className="btn-primary btn-md w-full">
            {bulk.pending ? '넣는 중…' : `남은 ${restMoves.length}곳 한 번에 넣기`}
          </button>
          {bulk.error != null && <ErrorText message="일정에 반영하지 못했어요" error={bulk.error} />}
        </div>
      )}
      {bulkStale && (
        <p role="alert" className="break-keep text-body text-warn-text">
          {staleFixText}
        </p>
      )}
      {fixes.length > 0 && (
        <ul aria-label="고칠 점" className="space-y-2">
          {fixes.map((fix) => (
            <li key={fix.id}>
              <FixCard mapId={mapId} runId={run.id} runStale={run.stale || bulkStale} fix={fix} names={names} dayName={dayName} onRetry={onRetry} />
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
  runStale,
  fix,
  names,
  dayName,
  onRetry,
}: {
  mapId: string
  runId: string
  runStale: boolean
  fix: CourseFixDto
  names: Map<string, string>
  dayName: (date: string | null) => string
  onRetry: () => void
}) {
  const queryClient = useQueryClient()
  const applied = useAppliedFixStore((s) => s.applied[runId]?.includes(fix.id) ?? false)
  // run.stale(새로고침 뒤나 다른 구성원이 일정을 바꾼 뒤)이면 「반영」은 version 을 새로 읽어 409 가 나지 않으니 옛 카드가 그대로 저장된다 — 막는다.
  // 다른 카드를 반영했으면 이 카드는 반영 전 일정 기준이라 그대로 누르면 틀린 이동이 저장된다 — 「반영」을 막고 다시 점검하게 한다.
  const otherApplied = useAppliedFixStore((s) => (s.applied[runId]?.length ?? 0) > 0)
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
      // false 면 run 이 stale 로 바뀌어 캐시에 들어갔다 — 카드가 「다시 점검」으로 바뀐다.
      if (await applyFix(queryClient, mapId, runId, fix.moves)) mark(runId, fix.id)
      setState({ pending: false, error: null })
    } catch (error) {
      setState({ pending: false, error })
    }
  }

  return (
    <article className={`space-y-2 rounded-xl bg-surface p-3 ring-1 ring-ink-200 ${fix.strength === 'hard' ? 'border-l-4 border-[var(--warn-line)]' : ''}`}>
      <span className={`tag ${fix.strength === 'hard' ? 'tag-warn' : 'tag-neutral'}`}>{fix.strength === 'hard' ? '꼭 고칠 것' : '선호'}</span>
      <h3 className="break-keep text-base font-bold text-ink-900">{fix.text}</h3>

      {movable ? (
        <>
          <ul className="space-y-1 rounded-lg bg-ink-50 p-2 text-body text-ink-700">
            {fix.moves.map((m) => (
              <li key={m.pin_id} className="flex flex-wrap items-center gap-x-1">
                <span className="font-semibold text-ink-900">{names.get(m.pin_id) ?? '이 장소'}</span>:<span>{dayName(m.from_date)}</span>
                <span className="sr-only">에서</span>
                <ArrowRight size={12} aria-hidden="true" />
                <span>{dayName(m.to_date)}</span>
                <span className="sr-only">로</span>
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
          ) : stale || otherApplied || runStale ? (
            <div className="space-y-2">
              <p role={stale ? 'alert' : undefined} className="break-keep text-body text-warn-text">
                {staleFixText}
              </p>
              <button type="button" onClick={onRetry} className="btn-outline btn-md">
                다시 점검
              </button>
            </div>
          ) : (
            <button type="button" onClick={() => void apply()} disabled={state.pending} className="btn-primary btn-md">
              {state.pending ? '반영하는 중…' : fill ? `${dayName(fix.moves[0].to_date)}에 넣기` : '반영'}
            </button>
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
