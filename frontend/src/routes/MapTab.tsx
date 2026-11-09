import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router'

import ErrorText from '@/ErrorText'
import { useMeQuery } from '@/features/auth/queries'
import CardSkeleton from '@/ui/CardSkeleton'
import ProgressBar from '@/ui/ProgressBar'
import EmptyState from '@/ui/EmptyState'
import SheetTitle from '@/ui/SheetTitle'
import TaskProgress from '@/ui/TaskProgress'
import AloneInvite from '@/features/map/AloneInvite'
import EmptyMap from '@/features/map/EmptyMap'
import { OnboardingBody, OnboardingHeader, type OnboardingKind } from '@/features/map/Onboarding'
import { filterPins, type Pin } from '@/features/map/model'
import ReactionHelp from '@/features/map/ReactionHelp'
import { CategoryChips, PinFilterBar } from '@/features/map/PinFilterControls'
import NewSinceBanner from '@/features/map/NewSinceBanner'
import { newsLines, opinionCount, useNewSince } from '@/features/map/newSince'
import PinList, { type CardNews } from '@/features/map/PinList'
import { usePinFilters } from '@/features/map/usePinFilters'
import { PinDetailBody, PinDetailHeader } from '@/features/map/PinDetail'
import PinUnavailable from '@/features/map/PinUnavailable'
import { ImportButton } from '@/features/kakaoImport/ImportSheet'
import { usePinSelection } from '@/features/map/usePinSelection'
import { useCountsQuery, usePinsQuery } from '@/features/map/queries'
import { useMapQuery, useMembersQuery } from '@/features/maps/queries'
import { useSourcePlacesQuery } from '@/features/search/queries'
import { SearchResultsBody, SearchResultsHeader } from '@/features/search/SearchResults'
import { useSearchStore } from '@/features/search/searchStore'
import { useSheetStore } from '@/features/shell/sheetStore'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { useIsDesktop } from '@/features/shell/useIsDesktop'

/**
 * 마킹된 장소 탭은 조립만 한다. 실제 내용은 전부 `features/map/` 안에 있다.
 * 새 기능은 이 파일을 키우지 말고 `features/map/` 에 파일을 더해서 여기서 끼운다.
 */
export default function MapTab() {
  const { mapId } = useShell()
  const { selectedPinId, selectPin } = usePinSelection()
  const { data: pins, isPending, error, refetch } = usePinsQuery(mapId)
  const counts = useCountsQuery(mapId).data
  const setStage = useSheetStore((s) => s.setStage)
  const stage = useSheetStore((s) => s.stages.map)
  const desktop = useIsDesktop()
  const map = useMapQuery(mapId).data
  const mapTitle = map?.title
  const memberCount = map?.memberCount ?? 0
  const members = useMembersQuery(mapId).data ?? []
  // 마지막으로 본 뒤 새로 생긴 핀·의견(#1454). 지도 점(MapLayout)과 같은 기준을 본다.
  const newSince = useNewSince(mapId, pins, useMeQuery().data?.id)
  const cardNews = new Map<string, CardNews>()
  for (const [id, n] of newSince.news) {
    const pin = pins?.find((p) => p.id === id)
    const nameOf = (r: { user_id: string; display_name?: string }) => members.find((m) => m.userId === r.user_id)?.name ?? r.display_name ?? '구성원'
    cardNews.set(id, { newPin: n.newPin, lines: pin ? newsLines(n, nameOf, (chip) => newSince.chipLabel(pin.category, chip)) : [] })
  }
  const { filters, setFilter, clear } = usePinFilters()
  const sorted = pins && filterPins(pins, filters, memberCount)
  // 순서는 필터·정렬을 바꾸거나 핀이 늘고 줄 때만 다시 매긴다. 의견 수만 바뀌었을 땐 그대로 둬서
  // 방금 의견을 남긴 카드가 맨 위로 튀지 않게 한다(#308).
  const orderKey = sorted ? `${filters.category}|${filters.createdBy}|${filters.kind}|${filters.opinion}|${filters.sort}|${sorted.map((p) => p.id).sort().join(',')}` : ''
  const [order, setOrder] = useState<{ key: string; ids: string[] } | null>(null)
  if (sorted && order?.key !== orderKey) setOrder({ key: orderKey, ids: sorted.map((p) => p.id) })
  const shown = sorted && order?.key === orderKey ? order.ids.map((id) => sorted.find((p) => p.id === id)).filter((p) => p !== undefined) : sorted
  const search = useSearchStore()
  const found = useSourcePlacesQuery(search.source, search.near).data?.places
  const filtered = Boolean(filters.category || filters.createdBy || filters.kind || filters.opinion)
  const [params, setParams] = useSearchParams()
  const onboarding = params.get('onboarding') as OnboardingKind | null

  const closeOnboarding = useCallback(() => {
    const next = new URLSearchParams(params)
    next.delete('onboarding')
    setParams(next, { replace: true })
  }, [params, setParams])

  // 온보딩은 시트 2단계로 띄우고, 접으면 닫힌다(Figma 3절 — 온보딩을 접으면 탭 1단계로).
  useEffect(() => {
    if (onboarding) setStage('map', 2)
  }, [onboarding, setStage])
  // "접었을 때"만 닫는다. 처음 들어올 때 이전 단계가 1이었던 건 접은 게 아니다.
  const prevStage = useRef(stage)
  useEffect(() => {
    if (onboarding && prevStage.current !== 1 && stage === 1) closeOnboarding()
    prevStage.current = stage
  }, [onboarding, stage, closeOnboarding])

  // 핀을 고르면 상세가 2단계로 올라온다(최종기획안 4절 "핀 상세").
  useEffect(() => {
    if (selectedPinId) setStage('map', 2)
  }, [selectedPinId, setStage])

  const selectedPin = pins?.find((pin) => pin.id === selectedPinId)
  // 목록을 다 받은 뒤에도 없으면 볼 수 없는 핀이다. 로딩 중이나 실패 중에는 판단하지 않는다.
  const unavailable = Boolean(selectedPinId) && !selectedPin && !isPending && !error

  // 검색은 잠깐 하는 작업이라 다른 화면(상세·온보딩)보다 앞에 온다. 닫으면 원래 화면으로 돌아간다.
  if (search.source) {
    return (
      <TabSheet tab="map" header={<SearchResultsHeader count={found ? found.length : null} />}>
        <SearchResultsBody mapId={mapId} pins={pins ?? []} />
      </TabSheet>
    )
  }

  if (onboarding && mapTitle) {
    return (
      <TabSheet tab="map" header={<OnboardingHeader kind={onboarding} mapTitle={mapTitle} />}>
        <OnboardingBody mapId={mapId} kind={onboarding} onDone={closeOnboarding} />
      </TabSheet>
    )
  }

  if (selectedPin) {
    return (
      <TabSheet
        tab="map"
        expandOnScroll
        header={<PinDetailHeader pin={selectedPin} mapId={mapId} onBack={() => selectPin(null)} />}
      >
        <PinDetailBody pin={selectedPin} mapId={mapId} members={members} onDone={() => selectPin(null)} />
      </TabSheet>
    )
  }

  return (
    <TabSheet
      tab="map"
      header={
        <>
          <div className="flex items-center justify-between gap-2">
            <SheetTitle>마킹된 장소</SheetTitle>
            <ImportButton mapId={mapId} />
          </div>
          {/* 넓은 화면은 단계가 없고 칩이 지도 영역 왼쪽 위에 있다(#338). */}
          {stage === 3 && !desktop && <CategoryChips value={filters.category} onChange={(c) => setFilter('category', c)} className="mt-2" />}
          {pins && pins.length > 0 && <PinFilterBar filters={filters} members={members} pins={pins} onChange={setFilter} />}
          <div className="mt-2 flex items-center gap-1">
            <p className="text-xs text-ink-500">{isPending ? '불러오는 중…' : `${shown?.length ?? 0}곳`}</p>
            {/* 목록 줄의 ♥·반대·? 표시가 무엇인지(#1030). */}
            {pins && pins.length > 0 && <ReactionHelp />}
          </div>
          {/* 지도 전체 참여율 — 글로만 적던 비율을 막대로도 보인다(#1539). */}
          {counts && counts.members_total > 0 && (
            <ProgressBar
              label={`${counts.members_total}명 중 ${counts.members_with_opinion}명이 의견을 남겼어요`}
              value={counts.members_with_opinion}
              max={counts.members_total}
              className="mt-2"
            />
          )}
        </>
      }
    >
      {unavailable && <PinUnavailable onClose={() => selectPin(null)} />}
      {isPending && <CardSkeleton />}
      {error && (
        <div className="space-y-2">
          <ErrorText message="핀을 불러오지 못했어요" error={error} />
          <button type="button" onClick={() => void refetch()} className="btn-outline btn-sm">
            다시 불러오기
          </button>
        </div>
      )}
      {pins?.length === 0 && <EmptyMap />}
      {pins && pins.length > 0 && shown?.length === 0 && filtered && (
        <FilterEmpty who={members.find((m) => m.userId === filters.createdBy)?.name} category={filters.category} onClear={clear} />
      )}
      {newSince.since && pins && pins.length > 0 && (
        <NewSinceBanner
          since={newSince.since}
          newPins={[...newSince.news.values()].filter((n) => n.newPin).length}
          newOpinions={[...newSince.news.values()].reduce((sum, n) => sum + opinionCount(n), 0)}
          onDismiss={newSince.dismiss}
        />
      )}
      {/* 핀은 있는데 구성원이 나 하나면 초대를 권한다(기획안 6절, #1560). */}
      {pins && pins.length > 0 && memberCount === 1 && <AloneInvite mapId={mapId} />}
      {pins && filters.opinion !== 'none' && <MyOpinionProgress pins={pins} onOpen={selectPin} onShowLeft={() => setFilter('opinion', 'none')} />}
      {shown && shown.length > 0 && <PinList pins={shown} memberCount={memberCount} onSelect={selectPin} news={cardNews} />}
    </TabSheet>
  )
}

/** 필터 0곳(Figma) — 필터 때문에 비었다는 걸 알려주고 바로 풀 수 있게 한다. */
function FilterEmpty({ who, category, onClear }: { who?: string; category: string | null; onClear: () => void }) {
  const what = [who && `${who}님이 올린`, category].filter(Boolean).join(' ')
  return (
    <EmptyState
      title="필터에 맞는 핀이 없어요"
      action={
        <button type="button" onClick={onClear} className="btn-outline btn-md">
          필터 해제
        </button>
      }
    >
      {what} 핀은 아직 없어요
    </EmptyState>
  )
}

/** 할 일 카드에 보이는 줄 수. 남은 곳이 더 있으면 「남은 N곳 모두 보기」로 필터를 연다. */
const TASK_ROWS = 3

/**
 * 「내 의견 2/3곳」 — 확정되지 않은 핀 중 내가 의견을 남긴 수(#1547). 남은 곳이 있을 때만 그린다.
 * 확정된 핀은 의견을 안 남겨도 할 일로 보지 않는다(목록 카드의 「의견 남기기」와 같은 기준).
 * 줄은 끝낸 곳 하나(있으면)와 남은 곳 — 남은 곳을 누르면 그 핀이 열린다.
 */
export function MyOpinionProgress({ pins, onOpen, onShowLeft }: { pins: Pin[]; onOpen: (pinId: string) => void; onShowLeft: () => void }) {
  const open = pins.filter((p) => p.kind !== '확정')
  const doneList = open.filter((p) => p.my_reaction)
  const leftList = open.filter((p) => !p.my_reaction)
  if (leftList.length === 0) return null
  const name = (p: Pin) => p.place_name ?? '이름 없는 장소'
  const shownDone = doneList.slice(0, 1).map((p) => ({ key: p.id, label: name(p), done: true }))
  const shownLeft = leftList.slice(0, TASK_ROWS - shownDone.length).map((p) => ({ key: p.id, label: name(p), done: false, onClick: () => onOpen(p.id) }))
  const hidden = leftList.length - shownLeft.length
  return (
    <div className="mb-3">
      <TaskProgress
        title="내 의견"
        done={doneList.length}
        total={open.length}
        unit="곳"
        items={[...shownDone, ...shownLeft]}
        hint={`남은 ${leftList.length}곳에 의견을 남기면 AI 추천이 더 정확해져요`}
        more={
          hidden > 0 && (
            <button type="button" onClick={onShowLeft} className="btn-link shrink-0 text-sm">
              남은 {leftList.length}곳 모두 보기
            </button>
          )
        }
      />
    </div>
  )
}
