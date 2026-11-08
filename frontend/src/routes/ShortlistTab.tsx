import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import { dayOrdinal } from '@/features/course/model'
import { PinDetailBody, PinDetailHeader } from '@/features/map/PinDetail'
import { useEnrichPin } from '@/features/map/livePlaces'
import ReactionHelp from '@/features/map/ReactionHelp'
import { usePinsQuery } from '@/features/map/queries'
import { useMembersQuery } from '@/features/maps/queries'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { showToast } from '@/features/shell/toast'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import DayRoute from '@/features/shortlist/DayRoute'
import { useShortlistQuery } from '@/features/shortlist/queries'
import { useRouteStore } from '@/features/shortlist/routeStore'
import { scheduledIds, UNSET_DAY } from '@/features/shortlist/schedule'
import { closeSchedule, leaveScheduleTab, openSchedule, useDropHover, useScheduleOpen } from '@/features/shortlist/scheduleStore'
import ShortlistExport from '@/features/shortlist/ShortlistExport'
import ShortlistList from '@/features/shortlist/ShortlistList'
import { useScheduleEdit } from '@/features/shortlist/useTripSchedule'
import { Calendar } from '@/ui/DatePicker'
import EmptyState from '@/ui/EmptyState'
import SheetTitle from '@/ui/SheetTitle'
import Mark from '@/ui/Mark'
import Sentences from '@/ui/Sentences'

/**
 * 확정된 장소 탭(Figma 7절, 2026-11-03 일정으로 바뀜). 리스트는 아직 일정에 넣지 않은 확정 장소이고, 위에서 날을 고른 뒤 줄의 「넣기」로 그날에 넣는다.
 * 순서와 동선은 일정이 정한다 — 「동선 보기」를 켜면 본문이 그날 일정(`DayRoute`)이 되고 지도에 그날 순서대로 선이 그어진다.
 * 넓은 화면은 「일정 짜기」 패널(`SchedulePanelHost`)을 옆에 열어 끌어 넣는다. 몇 시에 어디는 정하지 않는다(범위 밖).
 * 일정은 서버에 있어 구성원이 함께 본다(#1172).
 */
export default function ShortlistTab() {
  const { mapId } = useShell()
  const shortlist = useShortlistQuery(mapId)
  const pins = usePinsQuery(mapId).data ?? []
  const members = useMembersQuery(mapId).data ?? []
  const routeOn = useRouteStore((s) => s.on)
  const setRouteOn = useRouteStore((s) => s.set)
  const [params, setParams] = useSearchParams()
  const enrich = useEnrichPin()
  const edit = useScheduleEdit(mapId)
  const hover = useDropHover()
  const desktop = useIsDesktop()
  const scheduleOpen = useScheduleOpen(mapId)
  const [putDay, setPutDay] = useState<string | null>(null)

  // 확정 탭을 떠나면 「일정 짜기」 패널을 닫는다.
  useEffect(() => () => leaveScheduleTab(), [mapId])

  // 확정 리스트 항목의 핀은 핀 목록 밖에서 온다 — 실시간 핀(#382)의 이름·좌표를 같은 값으로 얹는다.
  const all = (shortlist.data ?? []).map((i) => ({ ...i, pin: enrich(i.pin) }))
  const inSchedule = scheduledIds(edit.schedule)
  // 리스트는 일정에 아직 넣지 않은 곳이다. 넣은 곳은 「동선 보기」(그날 일정)와 「일정 짜기」 패널에 있다.
  const items = all.filter((i) => !inSchedule.has(i.pin.id))
  const scheduled = all.length - items.length
  const day = putDay && edit.dates.includes(putDay) ? putDay : edit.dates[0]
  const openPin = pins.find((p) => p.id === params.get('pin'))

  const setOpenPin = (pinId: string | null) => {
    const next = new URLSearchParams(params)
    if (pinId) next.set('pin', pinId)
    else next.delete('pin')
    setParams(next)
  }

  function toggleRoute() {
    if (!routeOn && scheduled === 0) return showToast('장소를 날짜별 일정에 넣으면 동선을 확인할 수 있어요')
    setRouteOn(!routeOn)
  }

  if (openPin) {
    return (
      <TabSheet
        tab="shortlist"
        expandOnScroll
        header={<PinDetailHeader pin={openPin} mapId={mapId} backLabel="확정된 장소" onBack={() => setOpenPin(null)} />}
      >
        <PinDetailBody pin={openPin} mapId={mapId} members={members} onDone={() => setOpenPin(null)} />
      </TabSheet>
    )
  }

  const subtitle = shortlist.isPending || (!routeOn && !edit.ready && !edit.error)
    ? '불러오는 중…'
    : routeOn
      ? '일정에 넣은 순서대로 보여요'
      : scheduled > 0
        ? `일정에 넣을 곳 ${items.length}곳, 넣은 곳 ${scheduled}곳`
        : `${items.length}곳`

  return (
    <TabSheet
      tab="shortlist"
      header={
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <SheetTitle>확정된 장소 모아보기</SheetTitle>
            <div className="mt-0.5 flex items-center gap-1">
              <p className="text-xs text-ink-500">{subtitle}</p>
              {/* 확정 리스트·일정·동선 보기가 무엇인지(멘토 리뷰 #1401, #1484). */}
              {all.length > 0 && <ReactionHelp on="shortlist" />}
            </div>
          </div>
          {all.length > 0 && (
            <div className="flex shrink-0 gap-2">
              {/* AI 코스 짜기는 따로 탭이다(「AI 코스」). 「일정 짜기」 패널은 넓은 화면에만 있다 — 휴대폰은 줄의 「넣기」로 넣고 동선 보기로 고친다. */}
              <button type="button" aria-pressed={routeOn} aria-disabled={!routeOn && scheduled === 0} onClick={toggleRoute} className="chip">
                동선 보기{routeOn && <Mark kind="check" size={14} />}
              </button>
              {desktop && (
                // 다시 누르면 닫힌다(패널의 ✕·Esc와 같다).
                <button type="button" aria-pressed={scheduleOpen} onClick={() => (scheduleOpen ? closeSchedule() : openSchedule(mapId))} className="chip">
                  일정 짜기
                </button>
              )}
            </div>
          )}
        </div>
      }
    >
      {shortlist.error && <ErrorText message="확정 리스트를 불러오지 못했어요" error={shortlist.error} />}
      {shortlist.data?.length === 0 && (
        <EmptyState
          title="아직 확정된 장소가 없어요"
          action={
            <Link to={`/maps/${mapId}`} className="btn-outline btn-md">
              마킹된 장소 보러 가기
            </Link>
          }
        >
          가기로 결정한 장소들이 이곳에 모여요. 마킹된 장소에서 확정 리스트에 넣어 보세요.
        </EmptyState>
      )}
      {all.length > 0 && routeOn && <DayRoute mapId={mapId} onOpen={setOpenPin} />}
      {all.length > 0 && !routeOn && (
        // 리스트 자리도 끌어 놓을 칸이다 — 「일정 짜기」 패널의 줄을 여기에 놓으면 일정에서 빠진다.
        <div
          data-day={UNSET_DAY}
          data-over={hover?.day === UNSET_DAY}
          className="drop-target space-y-3 rounded-xl pb-[100px] outline-offset-4"
        >
          {edit.error ? (
            <div className="space-y-2">
              <ErrorText message="일정을 불러오지 못했어요" error={edit.error} />
              <button type="button" onClick={edit.retry} className="btn-outline btn-sm">
                다시 불러오기
              </button>
            </div>
          ) : !edit.ready ? (
            <p className="text-sm text-ink-500">일정을 불러오는 중…</p>
          ) : items.length === 0 ? (
            <p className="break-keep text-sm text-ink-500">
              <Sentences text="모든 장소를 일정에 넣었어요. 동선 보기로 날짜별 경로를 확인해 보세요." />
            </p>
          ) : (
            <>
              {day ? (
                // 넣을 날을 먼저 고른다 — 여행 날짜만 고를 수 있는 달력이다. 그 밖의 날은 어둡게 막는다.
                <div role="group" aria-labelledby="put-day-label" className="rounded-xl border border-ink-200 bg-white p-3">
                  <p id="put-day-label" className="mb-1 flex items-baseline justify-between gap-2 text-sm font-bold text-ink-900">
                    넣을 날짜
                    <span className="text-xs font-semibold text-[var(--selected-text)]">{dayOrdinal(edit.dates.indexOf(day))}</span>
                  </p>
                  <Calendar
                    value={day}
                    min={edit.dates[0]}
                    max={edit.dates[edit.dates.length - 1]}
                    onPick={setPutDay}
                    dayName={(d) => (edit.dates.includes(d) ? dayOrdinal(edit.dates.indexOf(d)) : undefined)}
                    className="mx-auto w-full max-w-[19.25rem]"
                  />
                </div>
              ) : (
                <p className="text-sm text-ink-500"><Sentences text="여행 날짜를 정하면 일정을 짤 수 있어요" /></p>
              )}
              <ShortlistList
                items={items}
                dayLabel={day ? dayOrdinal(edit.dates.indexOf(day)) : ''}
                onPut={day ? (item) => edit.put([item.pin.id], [item.pin.place_name ?? '이 장소'], day) : undefined}
                onOpen={setOpenPin}
                onDrop={
                  desktop && scheduleOpen
                    ? (item, spot) => spot.day !== UNSET_DAY && edit.put([item.pin.id], [item.pin.place_name ?? '이 장소'], spot.day, spot.index)
                    : undefined
                }
              />
            </>
          )}
          <ShortlistExport mapId={mapId} />
        </div>
      )}
    </TabSheet>
  )
}
