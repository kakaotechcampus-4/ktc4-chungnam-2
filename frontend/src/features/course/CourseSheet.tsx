import { useState } from 'react'
import { Calendar } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import ErrorText from '@/ErrorText'
import { usePinsQuery } from '@/features/map/queries'
import { useEnrichPin } from '@/features/map/livePlaces'
import { useMapQuery } from '@/features/maps/queries'
import ModalSheet from '@/features/shell/ModalSheet'
import { useShortlistQuery } from '@/features/shortlist/queries'
import SheetTitle from '@/ui/SheetTitle'
import TextField from '@/ui/TextField'

import CourseRun from './CourseRun'
import { createErrorMessage, inProgressRunId, pinNames, pinPoints, REQUEST_MAX } from './model'
import { courseKeys, useCreateCourseMutation, useLatestCourseQuery } from './queries'

/**
 * 「AI 코스 짜기」 시트 — 진입(요청 한 줄) → 진행 → 결과가 한 시트 안에서 바뀐다.
 * 장소 이름은 맵 화면이 이미 받은 확정 리스트·핀 목록에서 찾는다(코스 응답은 pin_id 만 준다).
 */
export default function CourseSheet({ mapId, onClose }: { mapId: string; onClose: () => void }) {
  const [runId, setRunId] = useState<string | null>(null)
  const enrich = useEnrichPin()
  const shortlist = useShortlistQuery(mapId).data ?? []
  const pins = usePinsQuery(mapId).data ?? []
  // 확정 리스트의 핀(실시간 핀 이름 포함)을 먼저, 없으면 핀 목록에서.
  const all = [...shortlist.map((i) => enrich(i.pin)), ...pins]
  const names = pinNames(all)
  const points = pinPoints(all)

  return (
    <ModalSheet label="AI 코스 짜기" onClose={onClose}>
      {runId ? (
        <CourseRun runId={runId} names={names} points={points} onRetry={() => setRunId(null)} onClose={onClose} />
      ) : (
        <Entry mapId={mapId} onRun={setRunId} />
      )}
    </ModalSheet>
  )
}

function Entry({ mapId, onRun }: { mapId: string; onRun: (runId: string) => void }) {
  const [text, setText] = useState('')
  const queryClient = useQueryClient()
  const map = useMapQuery(mapId).data
  const latest = useLatestCourseQuery(mapId).data
  const create = useCreateCourseMutation(mapId)
  const known = createErrorMessage(create.error)

  function submit() {
    create.mutate(text, {
      onSuccess: (res) => onRun(res.course_run_id),
      // 이미 짜는 중이면 새로 만들지 않고 그 run 으로 간다.
      onError: (err) => {
        const running = inProgressRunId(err)
        if (running) onRun(running)
      },
    })
  }

  function openLatest() {
    if (!latest) return
    queryClient.setQueryData(courseKeys.run(latest.id), latest)
    onRun(latest.id)
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault()
        if (!create.isPending) submit()
      }}
      className="space-y-4"
    >
      <div>
        <SheetTitle>AI 코스 짜기</SheetTitle>
        <p className="mt-1 break-keep text-sm text-ink-500">확정 리스트의 장소를 날짜별로 나눠 순서를 짜 줘요. 지도와 확정 리스트는 바뀌지 않고, 결과는 나한테만 보여요</p>
      </div>
      {map && (
        <p className="flex items-center gap-1.5 text-sm text-ink-700">
          <Calendar size={16} aria-hidden="true" />
          <span className="sr-only">여행 날짜</span>
          {map.dates}
        </p>
      )}
      <div className="space-y-1.5">
        <label htmlFor="course-request" className="text-sm font-bold text-ink-900">
          요청 한 줄 <span className="font-normal text-ink-500">(선택)</span>
        </label>
        <TextField id="course-request" value={text} onChange={setText} maxLength={REQUEST_MAX} placeholder="둘째 날은 실내 위주로" clearLabel="요청 지우기" />
      </div>
      {known && <p role="alert" className="text-sm text-warn-text">{known}</p>}
      {create.error && !known && !inProgressRunId(create.error) && <ErrorText message="코스를 요청하지 못했어요" error={create.error} />}
      <div className="space-y-1">
        <button type="submit" disabled={create.isPending} className="btn-primary btn-lg w-full">
          {create.isPending ? '요청하는 중…' : '코스 짜기'}
        </button>
        {latest && (
          <div className="flex justify-center">
            <button type="button" onClick={openLatest} className="btn-link text-sm">
              {latest.status === 'queued' || latest.status === 'running' ? '짜는 중인 코스 보기' : '최근 코스 보기'}
            </button>
          </div>
        )}
      </div>
    </form>
  )
}
