import { useEffect } from 'react'

import ErrorText from '@/ErrorText'
import { dayLine, dayTitle } from '@/features/course/model'
import { useEnrichPin } from '@/features/map/livePlaces'
import SidePanel from '@/features/shell/SidePanel'
import CardSkeleton from '@/ui/CardSkeleton'
import EmptyState from '@/ui/EmptyState'
import Sentences from '@/ui/Sentences'

import { useShortlistQuery } from './queries'
import { scheduledIds } from './schedule'
import { ScheduleDayBox, ScheduleDayList } from './ScheduleDay'
import { closeSchedule, useScheduleOpen } from './scheduleStore'
import { useScheduleEdit } from './useTripSchedule'

/**
 * 「일정 짜기」 패널을 그리는 자리. 넓은 화면의 확정 탭에서만 지도 화면(MapLayout)에 둔다 — 휴대폰은 리스트 줄의 「넣기」로 넣고
 * 「동선 보기」로 고친다(2026-11-03). 탭을 떠나거나 다른 지도로 가면 닫힌다.
 * 열림은 스토어에 있어서 확정 탭 안이 핀 상세로 바뀌어도 닫히지 않는다. 옆 패널이라 지도 버튼·토스트를 숨기지 않는다.
 */
export function SchedulePanelHost({ mapId }: { mapId: string }) {
  const open = useScheduleOpen(mapId)
  useEffect(() => () => closeSchedule(), [mapId])
  if (!open) return null
  return (
    <SidePanel label="일정 짜기" onClose={closeSchedule}>
      <SchedulePanel mapId={mapId} />
    </SidePanel>
  )
}

/**
 * 여행 날짜마다 칸을 두고 일정을 짠다(넓은 화면 — 일정은 서버에 있어 구성원이 함께 본다). 시간은 정하지 않는다.
 * 넣을 장소는 왼쪽 확정 리스트에 있다 — 줄의 ≡ 를 끌어 칸에 놓거나 줄의 「넣기」로 넣는다. 칸 안의 줄은 끌어서 다른 날·다른 자리로,
 * 리스트 쪽에 놓으면 일정에서 빠진다. 그날 순서가 곧 「동선 보기」 순서다.
 */
export default function SchedulePanel({ mapId }: { mapId: string }) {
  const edit = useScheduleEdit(mapId)
  const shortlist = useShortlistQuery(mapId)
  const enrich = useEnrichPin()

  if (shortlist.error) return <ErrorText message="확정 리스트를 불러오지 못했어요" error={shortlist.error} />
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
  if (edit.dates.length === 0) return <p className="text-sm text-ink-500"><Sentences text="여행 날짜를 정하면 일정을 짤 수 있어요" /></p>
  const items = shortlist.data ?? []
  if (items.length === 0) {
    return <EmptyState title="아직 확정된 장소가 없어요">핀 찍기 탭에서 확정 리스트에 넣으면 여기서 날짜별로 나눌 수 있어요</EmptyState>
  }

  const byId = new Map(items.map((i) => [i.pin.id, enrich(i.pin)]))
  const name = (id: string) => byId.get(id)?.place_name ?? '이 장소'

  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-500">일정은 구성원 모두에게 보여요</p>
      {scheduledIds(edit.schedule).size === 0 && <p className="text-sm text-ink-700"><Sentences text="확정된 장소를 날짜별 칸으로 끌어 오거나 「넣기」를 눌러 하루 일정을 완성해 보세요" /></p>}
      {edit.dates.map((d, i) => {
        const ids = edit.schedule.days[d] ?? []
        return (
          <ScheduleDayBox key={d} day={d} title={dayTitle(d, i)} count={ids.length} color={dayLine(i).color}>
            <ScheduleDayList
              day={d}
              color={dayLine(i).color}
              ids={ids}
              nameOf={name}
              onTakeOut={(id) => edit.takeOut(id, name(id))}
              onDrop={(id, spot) => edit.drop(id, name(id), spot)}
              onShift={edit.shift}
              empty="비어 있어요"
            />
          </ScheduleDayBox>
        )
      })}
    </div>
  )
}
