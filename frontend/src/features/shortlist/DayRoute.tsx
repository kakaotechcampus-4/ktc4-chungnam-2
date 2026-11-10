import { ExternalLink } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { dayOrdinal, dayTitle } from '@/features/course/model'
import { useEnrichPin } from '@/features/map/livePlaces'
import { isPlaced } from '@/features/map/model'
import CardSkeleton from '@/ui/CardSkeleton'
import { Calendar } from '@/ui/DatePicker'
import Sentences from '@/ui/Sentences'

import { KAKAO_ROUTE_MAX, kakaoWalkUrl } from './model'
import { useShortlistQuery } from './queries'
import { useRouteStore } from './routeStore'
import { routeDay } from './schedule'
import { ScheduleDayBox, ScheduleDayList } from './ScheduleDay'
import { useScheduleEdit } from './useTripSchedule'

/**
 * 「동선 보기」를 켰을 때 확정 탭 본문 — 짜 둔 일정을 하루씩 본다(2026-11-03). 지도에는 그날 순서대로 선이 그어진다(MapLayout).
 * 여행 날짜만 고를 수 있는 달력(#1535, 장소를 넣은 날은 숫자 아래 점)으로 날을 고르고, 그날 장소를 순서대로 보이며 「빼기」와 순서 바꾸기(≡ 끌기·↑↓)를 한다. 휴대폰에서도 된다.
 * 길찾기는 카카오맵 새 창이다(앱 안 WebView 는 카카오 약관상 안 된다). 구간 시간은 서버 규칙이라 여기서 계산하지 않는다.
 */
export default function DayRoute({ mapId, onOpen }: { mapId: string; onOpen: (pinId: string) => void }) {
  const edit = useScheduleEdit(mapId)
  const shortlist = useShortlistQuery(mapId)
  const enrich = useEnrichPin()
  const chosen = useRouteStore((s) => s.day)
  const setDay = useRouteStore((s) => s.setDay)

  // 일정 조회가 실패하면 「불러오는 중」에 멈추지 않고 알린다(일정 짜기 패널과 같다).
  if (edit.error)
    return (
      <div className="space-y-2">
        <ErrorText message="일정을 불러오지 못했어요" error={edit.error} />
        <button type="button" onClick={edit.retry} className="btn-outline btn-sm">
          다시 불러오기
        </button>
      </div>
    )
  if (!edit.ready) return <CardSkeleton count={2} label="불러오는 중…" />
  const day = routeDay(edit.schedule, edit.dates, chosen)
  if (!day) return <p className="text-sm text-ink-500"><Sentences text="여행 날짜를 정하면 일정을 짤 수 있어요" /></p>

  const byId = new Map((shortlist.data ?? []).map((i) => [i.pin.id, enrich(i.pin)]))
  const name = (id: string) => byId.get(id)?.place_name ?? '이 장소'
  const ids = edit.schedule.days[day] ?? []
  const stops = ids.flatMap((id) => {
    const p = byId.get(id)
    return p && isPlaced(p) ? [{ name: name(id), lat: p.lat, lng: p.lng }] : []
  })
  const walk = kakaoWalkUrl(stops)
  const index = edit.dates.indexOf(day)

  return (
    <div className="space-y-3 pb-[100px]">
      {/* 넣을 날짜와 같은 달력이다. 장소를 넣은 날은 숫자 아래 점, 읽는 이름에는 「둘째 날, 2곳」. */}
      <div role="group" aria-labelledby="route-day-label" className="rounded-xl border border-ink-200 bg-surface p-3">
        <p id="route-day-label" className="mb-1 flex items-baseline justify-between gap-2 text-sm font-bold text-ink-900">
          볼 날짜
          <span className="text-xs font-semibold text-[var(--selected-text)]">{dayOrdinal(index)}</span>
        </p>
        <Calendar
          value={day}
          min={edit.dates[0]}
          max={edit.dates[edit.dates.length - 1]}
          onPick={setDay}
          marked={(d) => (edit.schedule.days[d]?.length ?? 0) > 0}
          dayName={(d) => {
            const i = edit.dates.indexOf(d)
            if (i < 0) return undefined
            const n = edit.schedule.days[d]?.length ?? 0
            return n > 0 ? `${dayOrdinal(i)}, ${n}곳` : dayOrdinal(i)
          }}
          className="mx-auto w-full max-w-[19.25rem]"
        />
      </div>
      <ScheduleDayBox day={day} title={dayTitle(day, index)} count={ids.length}>
        <ScheduleDayList
          day={day}
          ids={ids}
          nameOf={name}
          subOf={(id) => byId.get(id)?.category}
          onOpen={onOpen}
          onTakeOut={(id) => edit.takeOut(id, name(id))}
          onDrop={(id, spot) => edit.drop(id, name(id), spot)}
          onShift={edit.shift}
          empty="이 날은 비어 있어요"
        />
      </ScheduleDayBox>
      {walk && (
        <a href={walk} target="_blank" rel="noopener noreferrer" className="btn-link text-sm">
          카카오맵에서 길찾기 <ExternalLink size={14} aria-hidden="true" />
          {stops.length > KAKAO_ROUTE_MAX && <span className="font-normal text-ink-500"> · 앞 {KAKAO_ROUTE_MAX}곳</span>}
        </a>
      )}
      {stops.length < ids.length && <p className="text-xs text-ink-500"><Sentences text="위치를 모르는 핀은 동선에서 빠졌어요" /></p>}
      {stops.length === 1 && <p className="text-xs text-ink-500">2곳 이상이면 동선을 그려요</p>}
    </div>
  )
}
