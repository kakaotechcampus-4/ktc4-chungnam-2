import { useEffect, useId, useRef, useState } from 'react'
import { Calendar } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router'

import { CHANGED, START_PARAM } from '@/features/agent/actions'
import CreditConfirm from '@/features/credits/CreditConfirm'
import CreditGate from '@/features/credits/CreditGate'
import { creditBlock } from '@/features/credits/model'
import { useCreditsQuery } from '@/features/credits/queries'
import { usePinsQuery } from '@/features/map/queries'
import { useEnrichPin } from '@/features/map/livePlaces'
import { useMapQuery } from '@/features/maps/queries'
import { AiHeader } from '@/features/recommend/Readiness'
import { showToast } from '@/features/shell/toast'
import { routableCount } from '@/features/shortlist/model'
import { useShortlistQuery } from '@/features/shortlist/queries'
import ErrorText from '@/ErrorText'
import CardSkeleton from '@/ui/CardSkeleton'
import Notice from '@/ui/Notice'
import EmptyState from '@/ui/EmptyState'
import TextField from '@/ui/TextField'

import { useCourseViewStore } from './courseMapStore'
import CourseRun from './CourseRun'
import { createErrorMessage, pinNames, pinPoints, REQUEST_MAX, WALK_MAX_OPTIONS, walkLabel } from './model'
import { courseKeys, useCreateCourseMutation, useLatestCourseQuery } from './queries'

/**
 * 「AI 코스 짜기」 탭의 내용 — 입력(요청 한 줄) → 진행 → 결과가 한 자리에서 바뀐다. 예전에는 확정 탭 위에 뜨는 시트였다.
 * 보고 있는 코스는 지도별 화면 메모리(useCourseViewStore)에 둬서 탭을 오가도 이어진다.
 * 장소 이름은 맵 화면이 이미 받은 확정 리스트·핀 목록에서 찾는다(코스 응답은 pin_id 만 준다).
 */
export default function CourseBody({ mapId }: { mapId: string }) {
  const viewing = useCourseViewStore((s) => s.runs[mapId])
  const open = useCourseViewStore((s) => s.open)
  const close = useCourseViewStore((s) => s.close)
  const enrich = useEnrichPin()
  const shortlist = useShortlistQuery(mapId)
  const pins = usePinsQuery(mapId).data ?? []
  // 확정 리스트의 핀(실시간 핀 이름 포함)을 먼저, 없으면 핀 목록에서.
  const items = shortlist.data ?? []
  const all = [...items.map((i) => enrich(i.pin)), ...pins]
  const names = pinNames(all)
  const points = pinPoints(all)
  // 코스는 위치를 아는 확정 장소가 2곳부터다 — 확정 탭 「동선 보기」와 같은 함수로 센다.
  const routable = routableCount(items)
  // 요청 한 줄은 여기 둔다 — 결과의 「다시 점검」·「다시 짜기」로 입력에 돌아와도 쓴 글이 남는다.
  // 요청이 실패한 뒤 탭을 오가 새로 붙으면 실패한 요청의 글로 시작한다(「요청 고치기」).
  const [text, setText] = useState(() => useCourseViewStore.getState().failed[mapId]?.text ?? '')
  const [walkMax, setWalkMax] = useState<number | null>(() => useCourseViewStore.getState().failed[mapId]?.walkMax ?? null)

  if (viewing) {
    return (
      <div className="space-y-3">
        {viewing.redirected && <Notice>이미 짜고 있는 코스를 보여 드려요</Notice>}
        <CourseRun mapId={mapId} runId={viewing.runId} names={names} points={points} onRetry={() => close(mapId)} onClose={() => close(mapId)} />
      </div>
    )
  }
  if (shortlist.isPending) return <CardSkeleton count={2} label="불러오는 중…" />
  // 실패를 확정 0곳으로 읽으면 「장소가 2곳 이상 필요해요」 안내가 거짓으로 뜬다.
  if (shortlist.isError) return <LoadFailed error={shortlist.error} onRetry={() => void shortlist.refetch()} />
  return <Entry mapId={mapId} routable={routable} text={text} setText={setText} walkMax={walkMax} setWalkMax={setWalkMax} onRun={(id, fromInProgress = false) => open(mapId, id, fromInProgress)} />
}

function LoadFailed({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  return (
    <div className="space-y-2">
      <ErrorText message="확정 리스트를 불러오지 못했어요" error={error} />
      <button type="button" onClick={onRetry} className="btn-outline btn-sm">
        다시 불러오기
      </button>
    </div>
  )
}

/** 코스는 위치를 아는 확정 장소가 2곳부터다 — 안내 화면 제목과 버튼 아래 이유가 같은 말이다. */
const NOT_ENOUGH = '코스를 짜려면 확정된 장소가 2곳 이상 필요해요'

/** 위치를 아는 확정 장소가 2곳 미만이면 입력 대신 이유와 확정 탭으로 가는 길을 보인다(예전에는 칩을 누르면 토스트로 알렸다). */
function NotEnough({ mapId }: { mapId: string }) {
  return (
    <EmptyState
      title={NOT_ENOUGH}
      action={
        <Link to={`/maps/${mapId}/shortlist`} className="btn-outline btn-md">
          확정된 장소 보기
        </Link>
      }
    >
      마킹된 장소 탭에서 가고 싶은 곳들을 확정 리스트에 먼저 담아 보세요.
    </EmptyState>
  )
}

function Entry({
  mapId,
  routable,
  text,
  setText,
  walkMax,
  setWalkMax,
  onRun,
}: {
  mapId: string
  routable: number
  text: string
  setText: (text: string) => void
  walkMax: number | null
  setWalkMax: (min: number | null) => void
  onRun: (runId: string, fromInProgress?: boolean) => void
}) {
  const queryClient = useQueryClient()
  const map = useMapQuery(mapId).data
  const latestQuery = useLatestCourseQuery(mapId)
  const latest = latestQuery.data
  const create = useCreateCourseMutation(mapId)
  // 실패는 요청 훅이 지도별로 남긴다 — 탭을 오가 이 화면이 새로 붙어도 보인다.
  const failure = useCourseViewStore((s) => s.failed[mapId])
  const clearFail = useCourseViewStore((s) => s.clearFail)
  const error = failure?.error ?? null
  const known = createErrorMessage(error)
  // 크레딧을 쓰기 전에 묻는다(쓸 크레딧·남은 크레딧). 확인해야 요청한다.
  const [asking, setAsking] = useState(false)
  // 게스트는 버튼 자리가 카카오 안내라 묻지 않는다 — 요청 칸에서 Enter 를 눌러도 확인 창을 띄우지 않는다.
  const guest = creditBlock(useCreditsQuery().error)?.kind === 'guest'
  useAgentStart(routable, () => {
    if (!guest) setAsking(true)
  })

  // 만든 run 을 여는 것(이미 짜는 중이면 그 run 으로)은 요청 훅이 한다.
  const submit = () => create.mutate({ text, walkMax })

  function openLatest() {
    if (!latest) return
    queryClient.setQueryData(courseKeys.run(latest.id), latest)
    onRun(latest.id)
  }

  // 최근 코스를 받기 전에 안내 화면을 먼저 띄우면 받은 뒤 입력 화면으로 바뀌며 깜빡인다(#1127 리뷰).
  if (routable < 2 && latestQuery.isPending) return <p className="text-sm text-ink-500">불러오는 중…</p>
  if (routable < 2 && !latest && latestQuery.isError) return <LoadFailed error={latestQuery.error} onRetry={() => void latestQuery.refetch()} />
  if (routable < 2 && !latest) return <NotEnough mapId={mapId} />
  // 장소 부족(known)과 크레딧은 입력 화면에서 바로 고친다. 그 밖의 실패는 핑고가 알리고 같은 요청을 다시 보낸다.
  if (failure && !known && !creditBlock(error)) {
    return <RequestFailed pending={create.isPending} onRetry={() => create.mutate({ text: failure.text, walkMax: failure.walkMax })} onEdit={() => clearFail(mapId)} />
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!create.isPending && !guest) setAsking(true)
      }}
      className="space-y-4"
    >
      {map && (
        <p className="flex items-center gap-1.5 text-sm text-ink-700">
          <Calendar size={16} aria-hidden="true" />
          <span className="sr-only">여행 날짜</span>
          {map.dates}
        </p>
      )}
      <div className="space-y-1.5">
        <label htmlFor="course-request" className="text-sm font-bold text-ink-900">
          요청 사항 <span className="font-normal text-ink-500">(선택)</span>
        </label>
        <TextField id="course-request" value={text} onChange={setText} maxLength={REQUEST_MAX} placeholder="둘째 날은 실내 위주로" clearLabel="요청 지우기" />
      </div>
      <WalkPicker value={walkMax} onPick={setWalkMax} />
      {known && <p role="alert" className="text-sm text-warn-text">{known}</p>}
      <div className="space-y-1">
        {/* 게스트는 버튼 대신 카카오 안내, 잔액이 모자라면 후기 안내(확정 탭으로 간다). 확정 장소가 모자라면 막는다. */}
        <CreditGate feature="course" mapId={mapId} error={error} onCharged={() => clearFail(mapId)}>
          <button type="submit" disabled={create.isPending || routable < 2} className="btn-primary btn-lg w-full">
            {create.isPending ? '요청하는 중…' : '코스 짜기'}
          </button>
        </CreditGate>
        {/* 최근 코스가 있어 입력 화면이 보이지만 장소가 모자라면, 회색 버튼 아래에 이유를 적는다(#1127 리뷰). */}
        {routable < 2 && <p className="text-center text-xs text-ink-500">{NOT_ENOUGH}</p>}
        {latest && (
          <div className="flex justify-center">
            <button type="button" onClick={openLatest} className="btn-link text-sm">
              {latest.status === 'queued' || latest.status === 'running' ? '짜는 중인 코스 보기' : '최근 코스 보기'}
            </button>
          </div>
        )}
      </div>
      {asking && (
        <CreditConfirm
          feature="course"
          title="코스를 짤까요?"
          ok="코스 짜기"
          onOk={() => {
            setAsking(false)
            submit()
          }}
          onCancel={() => setAsking(false)}
        />
      )}
    </form>
  )
}

/**
 * 「핑고 AI 조언」 버튼(open_course)으로 들어오면 손으로 「코스 짜기」를 누를 때와 같이 한 번 시작한다(#1356) — 크레딧 확인 창부터다.
 * 추천 탭의 같은 버튼(Readiness useAgentStart)과 같은 방식이다. 그새 확정 장소가 모자라졌으면 시작하지 않고 「상황이 바뀌었어요」.
 */
function useAgentStart(routable: number, ask: () => void) {
  const [params, setParams] = useSearchParams()
  const wanted = params.has(START_PARAM)
  // 한 번만 시작한다 — ask 는 렌더마다 새로 만들어지고, 개발 모드(StrictMode)는 효과가 두 번 돈다.
  const started = useRef(false)
  useEffect(() => {
    if (!wanted || started.current) return
    started.current = true
    setParams(
      (p) => {
        p.delete(START_PARAM)
        return p
      },
      { replace: true },
    )
    if (routable < 2) showToast(CHANGED)
    else ask()
  }, [wanted, routable, ask, setParams])
}

/**
 * 코스 요청이 실패했다(장소 부족·크레딧 밖). 당황한 핑고 + 같은 요청 다시 보내기 · 요청 고치기.
 * 다시 보내기도 크레딧을 쓰는 요청이라 입력 화면처럼 먼저 묻는다.
 */
function RequestFailed({ pending, onRetry, onEdit }: { pending: boolean; onRetry: () => void; onEdit: () => void }) {
  const [asking, setAsking] = useState(false)
  return (
    <div className="space-y-3">
      <AiHeader title="코스를 요청하지 못했어요" sub="잠깐 문제가 생겼어요. 다시 눌러 주세요" mood="flustered" />
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={onEdit} disabled={pending} className="btn-neutral btn-lg">
          요청 고치기
        </button>
        <button type="button" onClick={() => setAsking(true)} disabled={pending} className="btn-primary btn-lg">
          {pending ? '요청하는 중…' : '다시 시도'}
        </button>
      </div>
      {asking && (
        <CreditConfirm
          feature="course"
          title="코스를 짤까요?"
          ok="코스 짜기"
          onOk={() => {
            setAsking(false)
            onRetry()
          }}
          onCancel={() => setAsking(false)}
        />
      )}
    </div>
  )
}

/**
 * 「하루 걷기」 — 하루에 걸을 시간의 상한(#1502). 고르면 코스가 그날 도보 합계를 그 안으로 맞춘다(대중교통 시간은 세지 않는다).
 * 「상관없음」이면 보내지 않아 서버 기본 상한을 쓴다.
 */
function WalkPicker({ value, onPick }: { value: number | null; onPick: (min: number | null) => void }) {
  const labelId = useId()
  return (
    <div className="space-y-1.5">
      <p id={labelId} className="text-sm font-bold text-ink-900">
        하루 걷기 <span className="font-normal text-ink-500">(선택)</span>
      </p>
      <div role="group" aria-labelledby={labelId} className="flex flex-wrap gap-2">
        <button type="button" aria-pressed={value === null} onClick={() => onPick(null)} className="chip">
          상관없음
        </button>
        {WALK_MAX_OPTIONS.map((m) => (
          <button key={m} type="button" aria-pressed={value === m} onClick={() => onPick(m)} className="chip">
            {walkLabel(m)}까지
          </button>
        ))}
      </div>
    </div>
  )
}
