import { useEffect } from 'react'
import { Link, useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import { PinDetailBody, PinDetailHeader } from '@/features/map/PinDetail'
import { useEnrichPin } from '@/features/map/livePlaces'
import { usePinsQuery } from '@/features/map/queries'
import { useMembersQuery } from '@/features/maps/queries'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { showToast } from '@/features/shell/toast'
import { move, routeSummary, type ShortlistItemDto } from '@/features/shortlist/model'
import {
  useAddToShortlistMutation,
  useRemoveFromShortlistMutation,
  useReorderShortlistMutation,
  useRouteMutation,
  useRouteQuery,
  useShortlistQuery,
} from '@/features/shortlist/queries'
import { useRouteStore } from '@/features/shortlist/routeStore'
import ShortlistList from '@/features/shortlist/ShortlistList'
import { josa } from '@/ui/josa'
import EmptyState from '@/ui/EmptyState'

/** 확정된 장소 탭(Figma 7절). 동선은 순서만 — 몇 시에 어디는 정하지 않는다(범위 밖). */
export default function ShortlistTab() {
  const { mapId } = useShell()
  const shortlist = useShortlistQuery(mapId)
  const pins = usePinsQuery(mapId).data ?? []
  const members = useMembersQuery(mapId).data ?? []
  const routeOn = useRouteStore((s) => s.on)
  const setRouteOn = useRouteStore((s) => s.set)
  const route = useRouteQuery(mapId, routeOn)
  const calc = useRouteMutation(mapId)
  const remove = useRemoveFromShortlistMutation(mapId)
  const add = useAddToShortlistMutation(mapId)
  const reorder = useReorderShortlistMutation(mapId)
  const [params, setParams] = useSearchParams()
  const enrich = useEnrichPin()
  // 확정 리스트 항목의 핀은 핀 목록 밖에서 온다 — 실시간 핀(#382)의 이름·좌표를 같은 값으로 얹는다.
  const items = (shortlist.data ?? []).map((i) => ({ ...i, pin: enrich(i.pin) }))
  // 서버는 좌표를 모르는 실시간 핀을 동선에서 뺀다 — 동선 계산 대상은 그 밖의 항목이다.
  const routable = items.filter((i) => i.pin.source !== 'live').length
  const hasLive = routable < items.length
  const openPin = pins.find((p) => p.id === params.get('pin'))

  const setOpenPin = (pinId: string | null) => {
    const next = new URLSearchParams(params)
    if (pinId) next.set('pin', pinId)
    else next.delete('pin')
    setParams(next)
  }

  // 동선 보기가 켜진 채로 확정 리스트가 바뀌면 남은 곳끼리 다시 긋는다(Figma '동선 보기 · 해제 후').
  // 서버는 스스로 다시 계산하지 않는다(#30) — 켜 둔 사람의 화면이 다시 부른다.
  // 항목 구성(id 목록)과 토글이 바뀔 때만 다시 계산한다 — 순서만 바꾼 건 동선과 무관하다(#30).
  const itemKey = items.map((i) => i.id).sort().join(',')
  const { mutate: recalc } = calc
  useEffect(() => {
    if (routeOn && routable >= 2) recalc()
  }, [routeOn, itemKey, routable, recalc])

  function toggleRoute() {
    if (!routeOn && routable < 2) return showToast(hasLive ? '위치를 아는 장소가 2곳부터 동선을 보여 줘요' : '2곳부터 동선을 보여 줘요')
    setRouteOn(!routeOn)
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

  const subtitle =
    routeOn && route.data?.length
      ? `${routeSummary(route.data)} (직선거리 기준)`
      : `${items.length}곳${items.length ? ' · 동선 순서대로 보여요' : ''}`

  return (
    <TabSheet
      tab="shortlist"
      header={
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-xl font-bold text-ink-900">확정된 장소 모아보기</h2>
            <p className="mt-0.5 text-xs text-ink-500">{shortlist.isPending ? '불러오는 중…' : subtitle}</p>
          </div>
          {items.length > 0 && (
            <button
              type="button"
              aria-pressed={routeOn}
              onClick={toggleRoute}
              className={`shrink-0 rounded-lg border px-3 py-1.5 text-sm font-semibold ${
                routeOn ? 'border-brand-600 bg-brand-100 text-brand-700' : 'border-ink-300 bg-white text-brand-600'
              }`}
            >
              동선 보기{routeOn && ' ✓'}
            </button>
          )}
        </div>
      }
    >
      {shortlist.error && <ErrorText message="확정 리스트를 불러오지 못했어요" error={shortlist.error} />}
      {calc.error && <ErrorText message="동선을 계산하지 못했어요" error={calc.error} />}
      {routeOn && hasLive && <p className="text-xs text-ink-500">장소 정보가 없는 핀은 위치를 몰라 동선에서 빠졌어요</p>}
      {shortlist.data?.length === 0 && (
        <EmptyState
          title="아직 확정된 장소가 없어요"
          action={
            <Link to={`/maps/${mapId}`} className="btn-outline px-4 py-2 text-sm">
              마킹된 장소 보러 가기
            </Link>
          }
        >
          마킹된 장소에서 「확정 리스트에 넣기」를 누르면 여기 모여요.
          <br />
          2곳 이상이면 동선도 볼 수 있어요
        </EmptyState>
      )}
      {items.length > 0 && (
        <ShortlistList
          items={items}
          onOpen={setOpenPin}
          onRemove={removeItem}
          onReorder={(from, to) => reorder.mutate(move(items, from, to), { onError: () => showToast('순서를 바꾸지 못했어요') })}
        />
      )}
    </TabSheet>
  )
}
