import { useState } from 'react'
import { Link } from 'react-router'
import { Bus, ExternalLink, Map as MapIcon } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { useMeQuery } from '@/features/auth/queries'
import { toPinCard, type Pin } from '@/features/map/model'
import { ReactionCounts } from '@/features/map/PinList'
import PinThumb from '@/features/map/PinThumb'
import { usePinsQuery } from '@/features/map/queries'
import { usePinSelection } from '@/features/map/usePinSelection'
import { useMembersQuery } from '@/features/maps/queries'
import { AiHeader } from '@/features/recommend/Readiness'
import { useSheetStore } from '@/features/shell/sheetStore'
import { KAKAO_ROUTE_MAX } from '@/features/shortlist/model'
import { openRoute } from '@/features/shortlist/routeStore'
import Notice from '@/ui/Notice'
import PingoLoading from '@/ui/PingoLoading'
import Sentences from '@/ui/Sentences'

import { useCourseMapStore } from './courseMapStore'
import {
  courseDrawings,
  daySummary,
  dayStops,
  showHoursKnown,
  uncheckedPlaceCount,
  dayTitle,
  FAILURE_TEXT,
  goalState,
  modeOf,
  stalePrompt,
  legLabel,
  outcomeText,
  transitLink,
  walkLinks,
  VIOLATION_LABEL,
  type CourseRunDto,
} from './model'
import { useCourseRunQuery } from './queries'
import FixCards from './FixCards'
import WorkLog from './WorkLog'

/**
 * 한 번의 코스 run 화면. 끝나기 전엔 진행(작업 기록이 늘어남), done 이면 결과, failed 면 실패 안내.
 * 결과는 요청한 사람에게만 보이고, 지도와 확정 리스트는 바꾸지 않는다.
 */
type Points = Map<string, { lat: number; lng: number }>

export default function CourseRun({ mapId, runId, names, points, onRetry, onClose }: { mapId: string; runId: string; names: Map<string, string>; points: Points; onRetry: () => void; onClose: () => void }) {
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

  if (run.status === 'done') return <Result mapId={mapId} run={run} names={names} points={points} onRetry={onRetry} onClose={onClose} />
  if (run.status === 'failed') return <Failed run={run} onRetry={onRetry} onClose={onClose} />
  // 진행 중에 조회가 실패하면(이전 data 는 남는다) 폴링이 멈추므로, 진행 화면 아래에서 다시 불러오게 한다.
  return <Progress run={run} error={query.isError ? query.error : null} onRetryLoad={() => void query.refetch()} />
}

function Progress({ run, error, onRetryLoad }: { run: CourseRunDto; error: Error | null; onRetryLoad: () => void }) {
  return (
    <div className="space-y-3">
      <AiHeader title="코스를 짜고 있어요" sub="진행 상황을 한 줄씩 보여 드려요" mood="thinking" />
      <WorkLog steps={run.steps} running />
      {error && (
        <div className="space-y-2">
          <ErrorText message="진행 상황을 불러오지 못했어요" error={error} />
          <button type="button" onClick={onRetryLoad} className="btn-outline btn-md w-full">
            다시 불러오기
          </button>
        </div>
      )}
    </div>
  )
}

function Failed({ run, onRetry, onClose }: { run: CourseRunDto; onRetry: () => void; onClose: () => void }) {
  return (
    <div className="space-y-3">
      <AiHeader title="코스를 만들지 못했어요" sub={FAILURE_TEXT} mood="flustered" />
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

function Result({ mapId, run, names, points, onRetry, onClose }: { mapId: string; run: CourseRunDto; names: Map<string, string>; points: Points; onRetry: () => void; onClose: () => void }) {
  const [showLog, setShowLog] = useState(false)
  const drawings = courseDrawings(run, points)
  const showCourse = useCourseMapStore((s) => s.show)
  const setStage = useSheetStore((s) => s.setStage)

  // 지도에 날짜별 선을 긋고, 시트를 접어 지도와 범례(탭 머리)가 보이게 한다. 결과는 그대로 남아 다시 펼치면 보인다.
  // 「동선 보기」는 확정 탭에만, 코스 선은 AI 코스 탭에만 그려서 둘이 겹치지 않는다.
  function showOnMap() {
    showCourse(mapId, drawings)
    setStage('course', 1)
  }
  const name = (pinId: string) => names.get(pinId) ?? '이 장소'
  const hoursTag = showHoursKnown(run)
  const unchecked = uncheckedPlaceCount(run)
  const mode = modeOf(run)
  // 머리 둘째 줄 — 할 일과 문제의 수(#1714). 없으면 예전 안내 문구.
  const fixCount = mode === 'plan' ? 0 : (run.fixes?.length ?? 0)
  const summary = [fixCount > 0 && `고칠 점 ${fixCount}`, run.violations.length > 0 && `지키지 못한 조건 ${run.violations.length}`].filter(Boolean).join(', ')

  return (
    <div className="space-y-4">
      {/* 머리 문구는 서버 headline 그대로(#1237). 없으면(실서버 구현 전) 예전 outcome 문구. */}
      <AiHeader title={run.headline ?? (run.outcome ? outcomeText(run.outcome) : '코스를 짰어요')} sub={summary || (mode === 'review' ? undefined : '날짜별 순서와 이동 시간이에요')} mood="proud" />

      {run.stale && (
        <Notice
          action={
            <button type="button" onClick={onRetry} className="btn-outline btn-sm">
              다시 짜기
            </button>
          }
        >
          {stalePrompt}
        </Notice>
      )}

      {/* 지키지 못한 조건은 할 일보다 먼저 알린다(#1714, 배너). 예전엔 날짜별 순서 아래 맨 끝이었다. */}
      {run.violations.length > 0 && (
        <section aria-labelledby="course-violations" className="space-y-1.5 rounded-xl border border-[var(--warn-line)] bg-[var(--warn-bg)] p-3">
          <h3 id="course-violations" className="text-sm font-bold text-[var(--warn-text)]">
            지키지 못한 조건 {run.violations.length}
          </h3>
          <ul className="space-y-1">
            {run.violations.map((v, i) => (
              <li key={i} className="flex items-start gap-2 text-body text-ink-900">
                <span className="tag mt-px bg-surface text-[var(--warn-text)]">{VIOLATION_LABEL[v.kind]}</span>
                <span className="min-w-0 break-keep">{v.text}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {mode !== 'plan' && <FixCards mapId={mapId} run={run} names={names} onRetry={onRetry} />}

      {mode === 'review' && (
        <Link
          to={`/maps/${mapId}/shortlist`}
          // 점검 당시 days 대신 확정 탭의 현재 일정을 본다.
          onClick={openRoute}
          className="btn-outline btn-md w-full"
        >
          <MapIcon size={16} aria-hidden="true" /> 현재 일정 동선 보기
        </Link>
      )}

      {/* review 는 현재 일정 동선으로 연결하고, plan/fill 은 제안한 날짜별 순서를 보인다. */}
      {mode !== 'review' && (
        <Section title="날짜별 순서">
          <div className="space-y-2">
            {run.days.map((day, i) => (
              <DayCard key={day.date} mapId={mapId} day={day} index={i} names={names} points={points} hoursTag={hoursTag} />
            ))}
          </div>
          <p className="text-label text-ink-500">
            <Sentences text="이동 시간은 직선거리로 어림했어요. 자세한 길은 카카오맵에서 볼 수 있어요" />
          </p>
          {/* 장소마다 붙이지 않고 한 줄로 — 서버 작업 기록 「가게에 확인해야 하는 곳이 남았어요」와 맞춘다(루트 검수 #1127). */}
          {unchecked > 0 && <p className="text-label text-ink-500">영업시간 정보가 없는 {unchecked}곳은 방문 전에 확인해 주세요.</p>}
          {drawings.length > 0 && (
            <button type="button" onClick={showOnMap} className="btn-outline btn-md w-full">
              <MapIcon size={16} aria-hidden="true" /> 지도에서 날짜별로 보기
            </button>
          )}
        </Section>
      )}


      {run.goals.length > 0 && (
        <Section title="요청 사항">
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
        <p className="break-keep text-body text-ink-700">반영하지 못한 요청: {run.unmatched.join(', ')}</p>
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

      <div className="space-y-2">
        {/* "닫기"는 탭 안이라 무엇을 닫는지 모호했다 — 하는 일(입력으로 돌아가 새로 짜기)을 이름으로(#1714). */}
        <div className="flex items-center justify-between gap-2">
          <button type="button" aria-expanded={showLog} onClick={() => setShowLog(!showLog)} className="btn-link text-sm">
            {showLog ? '작업 기록 접기' : '작업 기록 보기'}
          </button>
          <button type="button" onClick={onClose} className="btn-outline btn-md">
            새로 짜기
          </button>
        </div>
        {showLog && <WorkLog steps={run.steps} running={false} />}
      </div>
    </div>
  )
}

/** 날짜 하나 — 방문 순서대로 장소, 장소 사이엔 도보·대중교통 분. 시간은 쓰지 않는다. 길찾기는 카카오맵 새 창이다. */
function DayCard({ mapId, day, index, names, points, hoursTag }: { mapId: string; day: CourseRunDto['days'][number]; index: number; names: Map<string, string>; points: Points; hoursTag: boolean }) {
  const stops = dayStops(day, names, points)
  const summary = daySummary(stops.flatMap((s) => (s.leg ? [s.leg] : [])))
  const links = walkLinks(stops)
  const pins = usePinsQuery(mapId).data
  const memberCount = useMembersQuery(mapId).data?.length ?? 0
  const myId = useMeQuery().data?.id
  const { selectPin } = usePinSelection()
  return (
    <article className="rounded-xl bg-surface p-3 ring-1 ring-ink-200">
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
                  <StopBody
                    name={s.name}
                    pin={pins?.find((p) => p.id === s.pinId)}
                    memberCount={memberCount}
                    myId={myId}
                    hoursKnown={hoursTag && s.hoursKnown}
                    onOpen={() => selectPin(s.pinId)}
                  />
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
              {l.cut && <span className="font-normal text-ink-500"> (앞 {KAKAO_ROUTE_MAX}곳만)</span>}
            </a>
          ))}
        </div>
      )}
    </article>
  )
}

/**
 * 장소 한 줄 — 사진, 이름, 분류와 동네, 메모, 의견 수. 누르면 핀을 골라(?pin=) 지도가 그 핀을 가운데로 옮기고
 * 이 탭 안에서 핀 상세가 열린다(MapLayout, CourseTab). 핀 목록에 없는 장소(지운 핀)는 이름만 둔다.
 */
function StopBody({ name, pin, memberCount, myId, hoursKnown, onOpen }: { name: string; pin?: Pin; memberCount: number; myId?: string; hoursKnown: boolean; onOpen: () => void }) {
  const hours = hoursKnown && <span className="tag tag-good mt-1">영업시간 확인됨</span>
  if (!pin) {
    return (
      <div className="min-w-0 flex-1">
        <p className="break-keep text-body font-semibold text-ink-900">{name}</p>
        {hours}
      </div>
    )
  }
  const meta = [pin.category, pin.neighborhood].filter(Boolean).join(' · ')
  return (
    <button type="button" onClick={onOpen} className="press -my-1 flex min-w-0 flex-1 gap-3 rounded-lg py-1 text-left">
      <PinThumb pin={pin} />
      <div className="min-w-0 flex-1">
        <p className="break-keep text-sm font-bold text-ink-900">{name}</p>
        <p className="text-xs text-ink-500">{meta}</p>
        {pin.memo && <p className="truncate text-xs text-ink-700">{pin.memo}</p>}
        <ReactionCounts card={toPinCard(pin, memberCount, myId)} className="mt-1" />
        {hours}
      </div>
    </button>
  )
}
