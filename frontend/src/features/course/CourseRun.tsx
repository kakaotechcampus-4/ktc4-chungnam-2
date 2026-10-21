import { useState } from 'react'
import { Bus, ExternalLink } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { AiHeader } from '@/features/recommend/Readiness'
import { KAKAO_ROUTE_MAX } from '@/features/shortlist/model'
import Notice from '@/ui/Notice'
import PingoLoading from '@/ui/PingoLoading'

import {
  daySummary,
  dayStops,
  dayTitle,
  failureText,
  goalState,
  legLabel,
  outcomeText,
  transitLink,
  walkLinks,
  VIOLATION_LABEL,
  type CourseRunDto,
} from './model'
import { useCourseRunQuery } from './queries'
import WorkLog from './WorkLog'

/**
 * 한 번의 코스 run 화면. 끝나기 전엔 진행(작업 기록이 늘어남), done 이면 결과, failed 면 실패 안내.
 * 결과는 요청한 사람에게만 보이고, 지도와 확정 리스트는 바꾸지 않는다.
 */
type Points = Map<string, { lat: number; lng: number }>

export default function CourseRun({ runId, names, points, onRetry, onClose }: { runId: string; names: Map<string, string>; points: Points; onRetry: () => void; onClose: () => void }) {
  const query = useCourseRunQuery(runId)
  const run = query.data

  if (!run) {
    if (query.error) {
      return (
        <div className="space-y-3">
          <ErrorText message="코스를 불러오지 못했어요" error={query.error} />
          <div className="grid grid-cols-2 gap-2">
            <button type="button" onClick={onClose} className="btn-neutral btn-lg">
              닫기
            </button>
            <button type="button" onClick={() => void query.refetch()} className="btn-outline btn-lg">
              다시 불러오기
            </button>
          </div>
        </div>
      )
    }
    return <PingoLoading label="코스를 불러오는 중…" />
  }

  if (run.status === 'done') return <Result run={run} names={names} points={points} onRetry={onRetry} onClose={onClose} />
  if (run.status === 'failed') return <Failed run={run} onRetry={onRetry} onClose={onClose} />
  return <Progress run={run} />
}

function Progress({ run }: { run: CourseRunDto }) {
  return (
    <div className="space-y-3">
      <AiHeader title="코스를 짜고 있어요" sub="누가 무엇을 했는지 한 줄씩 보여 줘요" mood="thinking" />
      <WorkLog steps={run.steps} running />
    </div>
  )
}

function Failed({ run, onRetry, onClose }: { run: CourseRunDto; onRetry: () => void; onClose: () => void }) {
  return (
    <div className="space-y-3">
      <AiHeader title="코스를 만들지 못했어요" sub={failureText(run.failure_code)} mood="sorry" />
      <WorkLog steps={run.steps} running={false} />
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={onClose} className="btn-neutral btn-lg">
          닫기
        </button>
        <button type="button" onClick={onRetry} className="btn-primary btn-lg">
          다시 짜기
        </button>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-bold text-ink-900">{title}</h3>
      {children}
    </section>
  )
}

function Result({ run, names, points, onRetry, onClose }: { run: CourseRunDto; names: Map<string, string>; points: Points; onRetry: () => void; onClose: () => void }) {
  const [showLog, setShowLog] = useState(false)
  const name = (pinId: string) => names.get(pinId) ?? '이 장소'
  const anyCheck = run.checks.length > 0 || run.days.some((d) => d.slots.some((s) => s.needs_check))

  return (
    <div className="space-y-4">
      <AiHeader title={run.outcome ? outcomeText(run.outcome) : '코스를 짰어요'} sub="순서와 이동 시간만 보여 줘요. 시간 배정은 하지 않아요" mood="happy" />

      {run.stale && (
        <Notice
          action={
            <button type="button" onClick={onRetry} className="btn-outline btn-sm">
              다시 짜기
            </button>
          }
        >
          확정 리스트가 바뀌었어요. 이 코스는 바뀌기 전 리스트로 짠 거예요
        </Notice>
      )}

      {run.goals.length > 0 && (
        <Section title="요청한 것">
          <ul className="space-y-1.5">
            {run.goals.map((g) => {
              const state = goalState(g)
              return (
                <li key={g.id} className="flex items-start gap-2 text-body text-ink-900">
                  <span className={`tag mt-px ${state.tag}`}>{state.label}</span>
                  <span className="min-w-0 break-keep">{g.label}</span>
                </li>
              )
            })}
          </ul>
        </Section>
      )}

      {run.unmatched.length > 0 && (
        <p className="break-keep text-body text-ink-700">반영하지 못했어요: {run.unmatched.map((u) => `「${u}」`).join(' ')}</p>
      )}

      <Section title="날짜별 순서">
        <div className="space-y-2">
          {run.days.map((day, i) => (
            <DayCard key={day.date} day={day} index={i} names={names} points={points} />
          ))}
        </div>
        <p className="text-label text-ink-500">이동 시간은 직선거리로 어림한 값이에요. 정확한 길은 카카오맵에서 확인하세요</p>
        {anyCheck && <p className="text-label text-ink-500">영업 여부를 모르는 장소는 가게에 직접 확인해 주세요</p>}
      </Section>

      {run.violations.length > 0 && (
        <Section title="지키지 못한 조건">
          <ul className="space-y-1.5">
            {run.violations.map((v, i) => (
              <li key={i} className="flex items-start gap-2 text-body text-ink-900">
                <span className="tag tag-bad mt-px">{VIOLATION_LABEL[v.kind]}</span>
                <span className="min-w-0 break-keep">{v.text}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {run.excluded.length > 0 && (
        <Section title="코스에서 빠진 장소">
          <ul className="space-y-1 text-body text-ink-700">
            {run.excluded.map((e) => (
              <li key={e.pin_id} className="break-keep">
                <span className="font-semibold text-ink-900">{name(e.pin_id)}</span> · {e.text}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <div>
        <button type="button" aria-expanded={showLog} onClick={() => setShowLog(!showLog)} className="btn-link text-sm">
          {showLog ? '작업 기록 접기' : '작업 기록 보기'}
        </button>
        {showLog && <WorkLog steps={run.steps} running={false} />}
      </div>

      <button type="button" onClick={onClose} className="btn-neutral btn-lg w-full">
        닫기
      </button>
    </div>
  )
}

/** 날짜 하나 — 방문 순서대로 장소, 장소 사이엔 도보·대중교통 분. 시간은 쓰지 않는다. 길찾기는 카카오맵 새 창이다. */
function DayCard({ day, index, names, points }: { day: CourseRunDto['days'][number]; index: number; names: Map<string, string>; points: Points }) {
  const stops = dayStops(day, names, points)
  const summary = daySummary(stops.flatMap((s) => (s.leg ? [s.leg] : [])))
  const links = walkLinks(stops)
  return (
    <article className="rounded-xl bg-white p-3 ring-1 ring-ink-200">
      <h4 className="text-base font-bold text-ink-900">{dayTitle(day.date, index)}</h4>
      {summary && <p className="text-xs text-ink-500">{summary}</p>}
      {stops.length === 0 ? (
        <p className="mt-1 text-body text-ink-500">이 날은 비어 있어요</p>
      ) : (
        <ol className="mt-2">
          {stops.map((s, i) => {
            const traffic = s.leg?.mode === 'transit' ? transitLink(s, stops[i + 1]) : null
            return (
              <li key={s.pinId}>
                <div className="flex items-start gap-2">
                  <span aria-hidden="true" className="mt-px flex size-5 shrink-0 items-center justify-center rounded-full bg-ink-100 text-xs font-bold text-ink-700">
                    {i + 1}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="break-keep text-body font-semibold text-ink-900">{s.name}</p>
                    {s.needsCheck && <span className="tag tag-warn mt-1">? 영업 확인 필요</span>}
                  </div>
                </div>
                {s.leg && (
                  <div className="my-1 ml-2.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 border-l-2 border-ink-200 pl-4 text-xs text-ink-500">
                    {s.leg.mode === 'transit' ? (
                      <span className="tag tag-neutral">
                        <Bus size={12} aria-hidden="true" /> {legLabel(s.leg)}
                      </span>
                    ) : (
                      <span>{legLabel(s.leg)}</span>
                    )}
                    {traffic && (
                      <a href={traffic} target="_blank" rel="noopener noreferrer" className="btn-link text-xs">
                        대중교통 길찾기 <ExternalLink size={12} aria-hidden="true" />
                      </a>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ol>
      )}
      {links.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-4">
          {links.map((l) => (
            <a key={l.url} href={l.url} target="_blank" rel="noopener noreferrer" className="btn-link text-sm">
              {l.label} <ExternalLink size={14} aria-hidden="true" />
              {l.cut && <span className="font-normal text-ink-500"> · 앞 {KAKAO_ROUTE_MAX}곳</span>}
            </a>
          ))}
        </div>
      )}
    </article>
  )
}
