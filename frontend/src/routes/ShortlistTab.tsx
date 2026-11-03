import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import { dayOrdinal } from '@/features/course/model'
import { PinDetailBody, PinDetailHeader } from '@/features/map/PinDetail'
import { FilterSelect } from '@/features/map/PinFilterControls'
import { useEnrichPin } from '@/features/map/livePlaces'
import { usePinsQuery } from '@/features/map/queries'
import { useMembersQuery } from '@/features/maps/queries'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { showToast } from '@/features/shell/toast'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import DayRoute from '@/features/shortlist/DayRoute'
import type { ShortlistItemDto } from '@/features/shortlist/model'
import { useAddToShortlistMutation, useRemoveFromShortlistMutation, useShortlistQuery } from '@/features/shortlist/queries'
import { useRouteStore } from '@/features/shortlist/routeStore'
import { scheduledIds, UNSET_DAY } from '@/features/shortlist/schedule'
import { closeSchedule, leaveScheduleTab, openSchedule, useDropHover, useScheduleOpen } from '@/features/shortlist/scheduleStore'
import ShortlistExport from '@/features/shortlist/ShortlistExport'
import ShortlistList from '@/features/shortlist/ShortlistList'
import { useScheduleEdit } from '@/features/shortlist/useTripSchedule'
import { josa } from '@/ui/josa'
import EmptyState from '@/ui/EmptyState'
import SheetTitle from '@/ui/SheetTitle'

/**
 * 확정된 장소 탭(Figma 7절, 2026-11-03 일정으로 바뀜). 리스트는 아직 일정에 넣지 않은 확정 장소이고, 체크박스로 골라 그날로 넣는다.
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
  const remove = useRemoveFromShortlistMutation(mapId)
  const add = useAddToShortlistMutation(mapId)
  const [params, setParams] = useSearchParams()
  const enrich = useEnrichPin()
  const edit = useScheduleEdit(mapId)
  const hover = useDropHover()
  const desktop = useIsDesktop()
  const scheduleOpen = useScheduleOpen(mapId)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [putDay, setPutDay] = useState<string | null>(null)

  // 확정 탭을 떠나면 「일정 짜기」 패널을 닫는다.
  useEffect(() => () => leaveScheduleTab(), [mapId])

  // 확정 리스트 항목의 핀은 핀 목록 밖에서 온다 — 실시간 핀(#382)의 이름·좌표를 같은 값으로 얹는다.
  const all = (shortlist.data ?? []).map((i) => ({ ...i, pin: enrich(i.pin) }))
  const inSchedule = scheduledIds(edit.schedule)
  // 리스트는 일정에 아직 넣지 않은 곳이다. 넣은 곳은 「동선 보기」(그날 일정)와 「일정 짜기」 패널에 있다.
  const items = all.filter((i) => !inSchedule.has(i.pin.id))
  const scheduled = all.length - items.length
  const picked = items.filter((i) => checked.has(i.pin.id))
  const day = putDay && edit.dates.includes(putDay) ? putDay : edit.dates[0]
  const openPin = pins.find((p) => p.id === params.get('pin'))

  const setOpenPin = (pinId: string | null) => {
    const next = new URLSearchParams(params)
    if (pinId) next.set('pin', pinId)
    else next.delete('pin')
    setParams(next)
  }

  function toggleRoute() {
    if (!routeOn && scheduled === 0) return showToast('장소를 골라 날짜에 넣으면 동선을 볼 수 있어요')
    setRouteOn(!routeOn)
  }

  function putPicked() {
    if (!day || picked.length === 0) return
    edit.put(
      picked.map((i) => i.pin.id),
      picked.map((i) => i.pin.place_name ?? '이 장소'),
      day,
    )
    setChecked(new Set())
  }

  function removeItem(item: ShortlistItemDto) {
    const name = item.pin.place_name ?? '이 장소'
    remove.mutate(item.id, {
      onSuccess: () =>
        showToast(`${name}${josa(name, '을', '를')} 확정 리스트에서 뺐어요`, {
          label: '되돌리기',
          onClick: () => add.mutate(item.pin.id, { onError: () => showToast('되돌리지 못했어요') }),
        }),
      onError: () => showToast('확정 리스트에서 빼지 못했어요'),
    })
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
      : `${items.length}곳${scheduled > 0 ? ` · 일정에 넣은 곳 ${scheduled}` : ''}`

  return (
    <TabSheet
      tab="shortlist"
      header={
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <SheetTitle>확정된 장소 모아보기</SheetTitle>
            <p className="mt-0.5 text-xs text-ink-500">{subtitle}</p>
          </div>
          {all.length > 0 && (
            <div className="flex shrink-0 gap-2">
              {/* AI 코스 짜기는 따로 탭이다(「AI 코스」). 「일정 짜기」 패널은 넓은 화면에만 있다 — 휴대폰은 체크박스로 넣고 동선 보기로 고친다. */}
              <button type="button" aria-pressed={routeOn} aria-disabled={!routeOn && scheduled === 0} onClick={toggleRoute} className="chip">
                동선 보기{routeOn && ' ✓'}
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
          마킹된 장소에서 「확정 리스트에 넣기」를 누르면 여기 모여요.
          <br />
          날짜에 나눠 넣으면 날짜별 동선도 볼 수 있어요
        </EmptyState>
      )}
      {all.length > 0 && routeOn && <DayRoute mapId={mapId} onOpen={setOpenPin} />}
      {all.length > 0 && !routeOn && (
        // 리스트 자리도 끌어 놓을 칸이다 — 「일정 짜기」 패널의 줄을 여기에 놓으면 일정에서 빠진다.
        <div
          data-day={UNSET_DAY}
          className={`space-y-3 rounded-xl pb-[100px] ${hover?.day === UNSET_DAY ? 'outline-2 outline-dashed outline-offset-4 outline-[var(--action-fill)]' : ''}`}
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
            <p className="break-keep text-sm text-ink-500">모든 장소를 일정에 넣었어요. 「동선 보기」에서 날짜별로 볼 수 있어요</p>
          ) : (
            <ShortlistList
              items={items}
              checked={checked}
              onCheck={(pinId, on) =>
                setChecked((s) => {
                  const next = new Set(s)
                  if (on) next.add(pinId)
                  else next.delete(pinId)
                  return next
                })
              }
              onOpen={setOpenPin}
              onRemove={removeItem}
              onDrop={
                desktop && scheduleOpen
                  ? (item, spot) => spot.day !== UNSET_DAY && edit.put([item.pin.id], [item.pin.place_name ?? '이 장소'], spot.day, spot.index)
                  : undefined
              }
            />
          )}
          {picked.length > 0 &&
            (day ? (
              // 고른 곳을 한 번에 그날 끝에 넣는다 — 리스트 순서대로.
              <div className="sticky bottom-0 flex items-center gap-2 border-t border-ink-200 bg-white py-3">
                <FilterSelect
                  ariaLabel="넣을 날짜"
                  value={day}
                  options={edit.dates.map((d, i) => ({ value: d, label: dayOrdinal(i) }))}
                  onChange={setPutDay}
                />
                <button type="button" onClick={putPicked} disabled={!edit.ready} className="btn-primary btn-md flex-1">
                  {picked.length}곳 넣기
                </button>
              </div>
            ) : (
              <p className="text-sm text-ink-500">여행 날짜를 정하면 일정을 짤 수 있어요</p>
            ))}
          <ShortlistExport mapId={mapId} />
        </div>
      )}
    </TabSheet>
  )
}
