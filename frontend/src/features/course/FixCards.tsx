import { useState } from 'react'
import { Link } from 'react-router'
import { ArrowRight, Check } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import BusyLabel from '@/ui/BusyLabel'
import DoneCard, { DoneCheck } from '@/ui/DoneCard'
import Mark from '@/ui/Mark'

import { applyFix } from './applyFix'
import { useAppliedFixStore } from './courseMapStore'
import { checkedOf, dayOrdinal, fixesOf, hasMoves, isFill, sortFixes, staleFixText, type CourseFixDto, type CourseRunDto } from './model'

/**
 * 고칠 점 카드와 "괜찮아요"(#1322, 결정 #1237). 문장은 모두 서버가 만든 것을 그대로 보인다.
 * "반영"은 카드마다 사람이 누른다 — 서버에 반영 API가 없어 지금 일정을 읽어 moves대로 옮기고 일정 API로 저장한다.
 * 머리 "고칠 점 N"의 N은 아직 반영하지 않은 카드 수다. 옮길 카드를 다 반영하면 완료 카드와 확정 탭 일정으로 가는 버튼을 띄운다(#1714).
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
  const movable = fixes.filter(hasMoves)
  const left = movable.filter((f) => !(applied?.includes(f.id) ?? false)).length
  const allDone = movable.length > 0 && left === 0
  return (
    <section aria-labelledby="course-fixes" className="space-y-2.5">
      {fixes.length > 0 && (
        <div className="flex items-baseline justify-between gap-2">
          <h3 id="course-fixes" className="text-sm font-bold text-ink-900">
            고칠 점 {left > 0 && <span className="text-link">{left}</span>}
          </h3>
          {left > 0 && <p className="text-xs text-ink-500">반영하면 확정 탭 일정에 들어가요</p>}
        </div>
      )}
      {/* 다 끝난 것을 회색 글로 두지 않는다 — 완료 카드와 다음 할 일(UI 참고 모음 "완료 표시"). */}
      {allDone && (
        <DoneCard
          title="고칠 점을 다 반영했어요"
          action={
            <Link to={`/maps/${mapId}/shortlist`} className="btn-outline btn-sm">
              일정 보기
            </Link>
          }
        >
          확정 탭 일정에 들어갔어요
        </DoneCard>
      )}
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
      {checked.length > 0 && <CheckedList items={checked.map((c) => c.text)} />}
    </section>
  )
}

/** 점검했고 문제가 없는 것 — 한 줄 "괜찮아요 N가지"로 접어 두고 눌러서 펼친다(#1714). 할 일 사이에서 초록 칸이 자리를 차지했다. */
function CheckedList({ items }: { items: string[] }) {
  const [open, setOpen] = useState(false)
  return (
    <section aria-label="괜찮아요">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="btn-link gap-1 text-body text-[var(--good-text)]">
        <Check size={14} aria-hidden="true" /> 괜찮아요 {items.length}가지
        {open ? <Mark kind="chevronUp" size={14} /> : <Mark kind="chevronDown" size={14} />}
      </button>
      {open && (
        <ul className="mt-1.5 space-y-1 rounded-xl bg-[var(--good-bg)] p-3">
          {items.map((t, i) => (
            <li key={i} className="break-keep text-body text-[var(--good-text)]">
              {t}
            </li>
          ))}
        </ul>
      )}
    </section>
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

  const tag = <span className={`tag ${fix.strength === 'hard' ? 'tag-warn' : 'tag-neutral'}`}>{fix.strength === 'hard' ? '꼭 고칠 것' : '선호'}</span>
  const moveText = (m: CourseFixDto['moves'][number]) => `${names.get(m.pin_id) ?? '이 장소'} ${dayName(m.from_date)} → ${dayName(m.to_date)}`

  // 반영한 카드는 한 줄로 접는다 — 초록 면 + 그려지는 완료 체크(UI 참고 모음 "완료 표시"). 회색 글 한 줄로 두지 않는다.
  if (applied) {
    return (
      <article className="flex items-center gap-2.5 rounded-xl bg-[var(--good-bg)] px-3 py-2.5">
        <DoneCheck size={20} />
        <p className="min-w-0 flex-1 break-keep text-body text-ink-900">
          <b className="text-[var(--good-text)]">반영했어요</b>
          <span className="text-ink-700"> {fix.moves.map(moveText).join(', ')}</span>
        </p>
        {tag}
      </article>
    )
  }

  // 지금 누를 수 있는 카드만 할 일 면(연파랑)이다. 다시 점검해야 하는 카드와 고치지 않기로 한 카드는 흰 면이다. 왼쪽 띠는 쓰지 않는다.
  const actionable = movable && !(stale || otherApplied || runStale)
  return (
    <article className={`space-y-2 rounded-xl p-3.5 ${actionable ? 'border-[1.5px] border-brand-600 bg-brand-50' : 'border border-ink-200 bg-surface'}`}>
      {tag}
      <h3 className="break-keep text-base font-bold text-ink-900">{fix.text}</h3>

      {movable ? (
        <>
          <ul className="space-y-1 rounded-lg bg-surface p-2 text-body text-ink-700">
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
          {stale || otherApplied || runStale ? (
            <div className="space-y-2">
              <p role={stale ? 'alert' : undefined} className="break-keep text-body text-warn-text">
                {staleFixText}
              </p>
              <button type="button" onClick={onRetry} className="btn-outline btn-md">
                다시 점검
              </button>
            </div>
          ) : (
            // 채움은 "남은 N곳 한 번에 넣기" 하나다 — 카드마다 채움이면 한 화면에 채운 버튼이 여럿이었다(#1714).
            <button type="button" onClick={() => void apply()} disabled={state.pending} aria-busy={state.pending} className="btn-outline btn-md w-full">
              <BusyLabel busy={state.pending} busyText="반영하는 중…">
                {fill ? `${dayName(fix.moves[0].to_date)}에 넣기` : '반영'}
              </BusyLabel>
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
