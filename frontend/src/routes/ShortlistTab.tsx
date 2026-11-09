import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import { dayOrdinal } from '@/features/course/model'
import { PinDetailBody, PinDetailHeader } from '@/features/map/PinDetail'
import { useEnrichPin } from '@/features/map/livePlaces'
import type { PinFilters } from '@/features/map/model'
import { CategoryChips } from '@/features/map/PinFilterControls'
import ReactionHelp from '@/features/map/ReactionHelp'
import { usePinsQuery } from '@/features/map/queries'
import { useMembersQuery } from '@/features/maps/queries'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import DayRoute from '@/features/shortlist/DayRoute'
import { useShortlistQuery } from '@/features/shortlist/queries'
import { useRouteStore } from '@/features/shortlist/routeStore'
import { scheduledIds, UNSET_DAY } from '@/features/shortlist/schedule'
import { closeSchedule, flashPin, leaveScheduleTab, openSchedule, useDropHover, useScheduleOpen } from '@/features/shortlist/scheduleStore'
import ShortlistExport from '@/features/shortlist/ShortlistExport'
import ShortlistList from '@/features/shortlist/ShortlistList'
import { useScheduleEdit } from '@/features/shortlist/useTripSchedule'
import CardSkeleton from '@/ui/CardSkeleton'
import CoachMark from '@/ui/CoachMark'
import { Calendar } from '@/ui/DatePicker'
import DoneCard from '@/ui/DoneCard'
import EmptyState from '@/ui/EmptyState'
import SheetTitle from '@/ui/SheetTitle'
import Mark from '@/ui/Mark'
import Sentences from '@/ui/Sentences'
import TaskProgress from '@/ui/TaskProgress'
import TipBubble from '@/ui/TipBubble'

/**
 * 장소 확정 탭(Figma 7절, 2026-11-03 일정으로 바뀜). 리스트는 아직 일정에 넣지 않은 확정 장소이고, 위에서 날을 고른 뒤 줄의 「넣기」로 그날에 넣는다.
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
  // 리스트를 분류로 걸러 본다(기획안 5-3, #1559). 일정·넣기는 거르지 않은 리스트 그대로다.
  const [category, setCategory] = useState<PinFilters['category']>(null)
  // 아직 못 쓰는 동선 보기를 누르면 이유를 그 버튼 아래 말풍선으로 잠깐 보인다(#1704, 전에는 화면 아래 토스트).
  const [routeTip, setRouteTip] = useState(false)
  useEffect(() => {
    if (!routeTip) return
    const t = setTimeout(() => setRouteTip(false), ROUTE_TIP_MS)
    return () => clearTimeout(t)
  }, [routeTip])

  // 확정 탭을 떠나면 「일정 짜기」 패널을 닫는다.
  useEffect(() => () => leaveScheduleTab(), [mapId])

  // 확정 리스트 항목의 핀은 핀 목록 밖에서 온다 — 실시간 핀(#382)의 이름·좌표를 같은 값으로 얹는다.
  const all = (shortlist.data ?? []).map((i) => ({ ...i, pin: enrich(i.pin) }))
  const inSchedule = scheduledIds(edit.schedule)
  // 리스트는 일정에 아직 넣지 않은 곳이다. 넣은 곳은 「동선 보기」(그날 일정)와 「일정 짜기」 패널에 있다.
  const items = all.filter((i) => !inSchedule.has(i.pin.id))
  const shown = category ? items.filter((i) => i.pin.category === category) : items
  const scheduled = all.length - items.length
  const allPlaced = edit.ready && !edit.error && all.length > 0 && items.length === 0
  const day = putDay && edit.dates.includes(putDay) ? putDay : edit.dates[0]
  const openPin = pins.find((p) => p.id === params.get('pin'))

  const setOpenPin = (pinId: string | null) => {
    const next = new URLSearchParams(params)
    if (pinId) next.set('pin', pinId)
    else next.delete('pin')
    setParams(next)
  }

  /**
   * 「넣기」 — 토스트만으로는 일정에 들어간 것이 잘 보이지 않았다. 넓은 화면은 「일정 짜기」 패널을 열고 넣은 줄을 잠깐 강조한다.
   * 휴대폰은 패널이 없어서 위 「일정」 카드의 그날 줄이 체크로 바뀌는 것(`done-check`)과 토스트로 알린다.
   */
  function putInDay(pinId: string, name: string, toDay: string, index?: number) {
    edit.put([pinId], [name], toDay, index)
    if (desktop && !scheduleOpen) openSchedule(mapId)
    flashPin(pinId)
  }

  function toggleRoute() {
    if (!routeOn && scheduled === 0) return setRouteTip(true)
    setRouteOn(!routeOn)
  }

  if (openPin) {
    return (
      <TabSheet
        tab="shortlist"
        expandOnScroll
        header={<PinDetailHeader pin={openPin} mapId={mapId} backLabel="장소 확정" onBack={() => setOpenPin(null)} />}
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
            <SheetTitle>장소 확정</SheetTitle>
            <div className="mt-0.5 flex items-center gap-1">
              <p className="text-xs text-ink-500">{subtitle}</p>
              {/* 확정 리스트·일정·동선 보기가 무엇인지(멘토 리뷰 #1401, #1484). */}
              {all.length > 0 && <ReactionHelp on="shortlist" />}
            </div>
          </div>
          {all.length > 0 && (
            <div className="flex shrink-0 gap-2">
              {/* AI 코스 짜기는 따로 탭이다(「AI 코스」). 「일정 짜기」 패널은 넓은 화면에만 있다 — 휴대폰은 줄의 「넣기」로 넣고 동선 보기로 고친다. */}
              {/* 다 넣었으면 완료 카드에 같은 버튼이 있어 여기서는 뺀다(#1680). 켜져 있을 때는 끄는 자리라 남긴다. */}
              {(routeOn || !allPlaced) && (
                <span className="relative">
                  <button type="button" aria-pressed={routeOn} aria-disabled={!routeOn && scheduled === 0} onClick={toggleRoute} className="chip">
                    동선 보기{routeOn && <Mark kind="check" size={14} />}
                  </button>
                  {routeTip && (
                    <TipBubble side="bottom" align="end">
                      장소를 날짜별 일정에 넣으면 동선을 확인할 수 있어요
                    </TipBubble>
                  )}
                </span>
              )}
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
      {/* 받는 동안 본문이 비어 있었다 — 리스트 줄 모양을 먼저 그린다(#1675). */}
      {shortlist.isPending && <CardSkeleton count={3} label="확정 리스트를 불러오는 중…" />}
      {shortlist.data?.length === 0 && (
        <EmptyState
          title="아직 확정된 장소가 없어요"
          action={
            <Link to={`/maps/${mapId}`} className="btn-outline btn-md">
              핀 찍기 탭으로 가기
            </Link>
          }
        >
          가기로 결정한 장소들이 이곳에 모여요. 핀 찍기 탭에서 확정 리스트에 넣어 보세요.
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
          {edit.ready && !edit.error && items.length > 0 && <ScheduleProgress dates={edit.dates} days={edit.schedule.days} onPick={setPutDay} />}
          {edit.error ? (
            <div className="space-y-2">
              <ErrorText message="일정을 불러오지 못했어요" error={edit.error} />
              <button type="button" onClick={edit.retry} className="btn-outline btn-sm">
                다시 불러오기
              </button>
            </div>
          ) : !edit.ready ? (
            <CardSkeleton count={2} label="일정을 불러오는 중…" />
          ) : items.length === 0 ? (
            // 다 넣었다는 걸 회색 글 한 줄로 두면 눈에 띄지 않았다 — 완료 카드 + 다음 할 일(동선 보기) 버튼.
            <DoneCard
              title="모든 장소를 일정에 넣었어요"
              action={
                <button type="button" onClick={toggleRoute} className="btn-outline btn-sm">
                  동선 보기
                </button>
              }
            >
              {emptyDays(edit.dates, edit.schedule.days) > 0 ? `빈 날이 ${emptyDays(edit.dates, edit.schedule.days)}일 있어요` : '날짜별 경로를 확인해 보세요'}
            </DoneCard>
          ) : (
            <>
              {day ? (
                // 넣을 날을 먼저 고른다 — 여행 날짜만 고를 수 있는 달력이다. 그 밖의 날은 어둡게 막는다.
                <div role="group" aria-labelledby="put-day-label" data-coach="shortlist-put" className="rounded-xl border border-ink-200 bg-surface p-3">
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
                    rangeWeeks
                    className="mx-auto w-full max-w-[19.25rem]"
                  />
                </div>
              ) : (
                <p className="text-sm text-ink-500"><Sentences text="여행 날짜를 정하면 일정을 짤 수 있어요" /></p>
              )}
              {day && (
                <CoachMark id="shortlist-put" target="shortlist-put" title="날짜를 고르고 넣기를 눌러요">
                  고른 날 일정 끝에 들어가요. 그날 순서는 동선 보기에서 바꿀 수 있어요
                </CoachMark>
              )}
              <CategoryChips value={category} onChange={(c) => setCategory(c as PinFilters['category'])} className="-mx-1 px-1" />
              {/* 필터 결과 없음 — 회색 글 한 줄은 눈에 안 띄고 푸는 길이 없었다(#1659). 마킹 탭 필터 0곳과 같은 모양. */}
              {shown.length === 0 && (
                <EmptyState
                  title="이 분류에는 확정된 곳이 없어요"
                  action={
                    <button type="button" onClick={() => setCategory(null)} className="btn-outline btn-md">
                      전체 보기
                    </button>
                  }
                />
              )}
              <ShortlistList
                items={shown}
                dayLabel={day ? dayOrdinal(edit.dates.indexOf(day)) : ''}
                onPut={day ? (item) => putInDay(item.pin.id, item.pin.place_name ?? '이 장소', day) : undefined}
                onOpen={setOpenPin}
                onDrop={
                  desktop && scheduleOpen
                    ? (item, spot) => spot.day !== UNSET_DAY && putInDay(item.pin.id, item.pin.place_name ?? '이 장소', spot.day, spot.index)
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

/** 장소를 하나도 넣지 않은 여행 날 수. */
const emptyDays = (dates: string[], days: Record<string, string[]>) => dates.filter((d) => !days[d]?.length).length

/** 동선 보기 말풍선이 떠 있는 시간. */
const ROUTE_TIP_MS = 3000

/** 일정 카드에 보이는 날 수. 넘치면 「외 N일」로 줄인다. */
const DAY_ROWS = 4

/**
 * 「일정 2/3일」 — 여행 날짜 중 장소를 하나라도 넣은 날의 수(#1547). 다 채우면 초록 막대와 한 줄만 남는다.
 * 날마다 한 줄 — 빈 날을 누르면 그날이 「넣을 날짜」로 골라진다.
 */
function ScheduleProgress({ dates, days, onPick }: { dates: string[]; days: Record<string, string[]>; onPick: (day: string) => void }) {
  const count = (d: string) => days[d]?.length ?? 0
  const filled = dates.length - emptyDays(dates, days)
  if (dates.length === 0) return null
  // 다 채우면 막대가 초록이 되고 줄 대신 한 줄로 알린다 — 사라지면 다 채운 것을 알 수 없었다.
  if (filled === dates.length) return <TaskProgress title="일정" done={filled} total={dates.length} unit="일" items={[]} hint="모든 날에 장소를 넣었어요" />
  const items = dates.slice(0, DAY_ROWS).map((d, i) =>
    count(d) > 0
      ? { key: d, label: `${dayOrdinal(i)} · ${count(d)}곳`, done: true }
      : { key: d, label: `${dayOrdinal(i)} · 비어 있어요`, done: false, onClick: () => onPick(d) },
  )
  const hidden = dates.length - items.length
  return (
    <TaskProgress
      title="일정"
      done={filled}
      total={dates.length}
      unit="일"
      items={items}
      hint={hidden > 0 ? `외 ${hidden}일이 더 있어요` : undefined}
    />
  )
}
