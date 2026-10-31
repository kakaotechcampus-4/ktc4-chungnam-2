import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useMatch, useNavigate, useParams } from 'react-router'
import { ChevronLeft, ChevronsLeft, ChevronsRight, FileText, MapPin, Search, Users, type LucideIcon } from 'lucide-react'

import AgentButton from '@/features/agent/AgentButton'
import MapCanvas, { type MapController } from '@/features/map/MapCanvas'
import { usePinSelection } from '@/features/map/usePinSelection'
import { byNewest, filterPins, isPlaced, timeAgo } from '@/features/map/model'
import { CategoryChips } from '@/features/map/PinFilterControls'
import { useLivePinResolver } from '@/features/map/livePlaces'
import { usePinsQuery, useResolveLivePin } from '@/features/map/queries'
import { useMapEvents } from '@/features/map/realtime'
import { usePinFilters } from '@/features/map/usePinFilters'
import MapSwitcher from '@/features/maps/MapSwitcher'
import NotificationBell from '@/features/notifications/NotificationBell'
import { useMapQuery } from '@/features/maps/queries'
import { useAiStore } from '@/features/recommend/aiStore'
import { useResultQuery } from '@/features/recommend/queries'
import { isLinkInput } from '@/features/search/model'
import { useSourcePlacesQuery } from '@/features/search/queries'
import { toRouteDrawings } from '@/features/shortlist/model'
import { useRouteQuery } from '@/features/shortlist/queries'
import { useRouteStore } from '@/features/shortlist/routeStore'
import { useCourseMapStore } from '@/features/course/courseMapStore'
import { useSearchStore } from '@/features/search/searchStore'
import { PANEL_W, RAIL_W, TAB_BAR_H } from '@/features/shell/layout'
import MapControls, { type ControlKey } from '@/features/shell/MapControls'
import { backAriaLabel, usePanelBackStore } from '@/features/shell/panelBack'
import ProfileModal, { ProfileMenu } from '@/features/shell/ProfileModal'
import { useSheetStore } from '@/features/shell/sheetStore'
import type { ShellContext } from '@/features/shell/shellContext'
import { ConnectionBanner } from '@/features/shell/TabSheet'
import { showToast } from '@/features/shell/toast'
import Toaster from '@/features/shell/Toaster'
import { useIsDesktop, useIsPc } from '@/features/shell/useIsDesktop'
import { PingoMark } from '@/ui/Pingo'
import { ClearButton } from '@/ui/TextField'

/** 넓은 화면 패널이 미끄러지는 시간. 패널·덧칠의 `duration-300` 과 같은 값이다. */
const PANEL_SLIDE_MS = 300

/**
 * 지도 하나 안의 화면(최종기획안 4절). 지도는 항상 떠 있고, 하단 탭 3개가 그 위 바텀시트 내용을 바꾼다.
 * 지도는 여기 한 번만 만든다 — 탭마다 만들면 탭을 바꿀 때마다 지도가 다시 뜬다.
 *
 * 넓은 화면(768px 이상, #338)은 왼쪽 480px(세로 탭 줄 72 + 높이 전체 내용 패널 408: 헤더·검색·탭 내용) + 오른쪽 지도 영역이다.
 * 태블릿(768~1023px)은 내용 패널만 360으로 좁다(#603).
 * 칩·연결 띠·지도 버튼·토스트는 지도 영역에 둔다. 패널과 모바일은 같은 트리를 쓰고 틀의 클래스만 바꾼다 —
 * 768px 경계를 넘나들어도 탭 내용(쓰던 의견 등)이 다시 마운트되지 않게.
 */
export default function MapLayout() {
  const { mapId = '' } = useParams()
  const navigate = useNavigate()
  const { selectedPinId, selectPin } = usePinSelection()
  const { data: allPins = [] } = usePinsQuery(mapId)
  const mapInfo = useMapQuery(mapId).data
  const memberCount = mapInfo?.memberCount ?? 0
  useLivePinResolver(allPins, mapInfo?.regionCenter, useResolveLivePin(mapId))
  const desktop = useIsDesktop()
  const panelW = useIsPc() ? PANEL_W.pc : PANEL_W.tablet
  const panelOpen = useSheetStore((s) => s.panelOpen)
  const setPanelOpen = useSheetStore((s) => s.setPanelOpen)
  const { filters, setFilter } = usePinFilters()
  const connection = useMapEvents(mapId)
  const onMarkingTab = useMatch('/maps/:mapId') !== null
  const onShortlistTab = useMatch('/maps/:mapId/shortlist') !== null
  // 마커와 목록이 같은 필터를 본다. 확정 탭은 확정 핀만, 다른 탭엔 필터가 없어 전부 보인다.
  const pins = onShortlistTab ? allPins.filter((p) => p.kind === '확정') : filterPins(allPins, filters, memberCount)
  const routeOn = useRouteStore((s) => s.on) && onShortlistTab
  const routes = useRouteQuery(mapId, routeOn).data
  const course = useCourseMapStore()
  // 「동선 보기」가 켜져 있으면 그게, 아니면 이 지도의 AI 코스(#683)가 확정 탭에서 선을 긋는다.
  const routeDrawings = useMemo(
    () => (routeOn && routes ? toRouteDrawings(routes, allPins) : onShortlistTab && course.mapId === mapId ? course.days : []),
    [routeOn, routes, allPins, onShortlistTab, course.mapId, course.days, mapId],
  )
  const markingStage = useSheetStore((s) => s.stages.map)
  const setStage = useSheetStore((s) => s.setStage)
  const search = useSearchStore()
  const [searchText, setSearchText] = useState('')
  // 결과 시트에서 「닫기」를 눌러도 입력칸에 글자가 남지 않게, 검색이 닫히면 같이 비운다(#351).
  const [lastSource, setLastSource] = useState(search.source)
  if (lastSource !== search.source) {
    setLastSource(search.source)
    if (search.source === null) setSearchText('')
  }
  const found = useSourcePlacesQuery(search.source, search.near).data?.places
  // 검색 결과 파란 핀 — 결과나 선택이 바뀔 때만 다시 그린다.
  const searchMarkers = useMemo(
    () =>
      (found ?? []).map((r, i) => ({
        n: i + 1,
        name: r.place_name,
        category: r.category,
        lat: r.lat,
        lng: r.lng,
        selected: r.place_id === search.selectedId,
        onClick: () => {
          useSearchStore.getState().select(r.place_id)
          // 접힌 패널에선 고른 결과를 볼 곳이 없다(넓은 화면).
          useSheetStore.getState().setPanelOpen(true)
        },
      })),
    [found, search.selectedId],
  )

  // AI 추천 탭에선 올리기 전 후보를 점선 핀으로 그린다(#843). 요청한 사람의 화면에만 있고 지도(핀 목록)는 바꾸지 않는다(가드레일 1).
  // 올린 후보는 이미 핀으로 떠 있어서 빼고, 좌표가 없는 후보도 뺀다. 결과는 추천 탭과 같은 캐시를 본다.
  const onRecommendTab = useMatch('/maps/:mapId/recommend') !== null
  const run = useAiStore((s) => s.runs[mapId])
  const result = useResultQuery(run?.status === 'done' ? run : undefined).data
  const candidateFocus = useAiStore((s) => s.focus)
  const candidates = useMemo(
    () =>
      onRecommendTab && run?.status === 'done'
        ? (result?.candidates ?? []).flatMap((c) =>
            c.visibility === 'published' || c.lat == null || c.lng == null
              ? []
              : [
                  {
                    id: c.id,
                    rank: c.rank,
                    name: c.place_name ?? '',
                    lat: c.lat,
                    lng: c.lng,
                    selected: c.id === candidateFocus?.id,
                    onClick: () => {
                      useAiStore.getState().focusCandidate(c.id)
                      // 접힌 패널에선 고른 카드를 볼 곳이 없다(넓은 화면).
                      useSheetStore.getState().setPanelOpen(true)
                    },
                  },
                ],
          )
        : [],
    [onRecommendTab, run?.status, result, candidateFocus?.id],
  )

  function submitSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = searchText.trim()
    if (!q) return
    // 검색은 마킹 탭의 일이다. 다른 탭에서 검색해도 마킹 탭으로 가서 결과를 보여준다.
    if (!onMarkingTab) navigate(`/maps/${mapId}`)
    const center = controller.current?.getCenter() ?? null
    // 지도 링크를 붙여넣었으면 이름 대신 링크로 장소를 찾는다(#487). 같은 결과 시트에서 핀을 찍는다.
    if (isLinkInput(q)) search.openLink(q, center)
    else search.submit(q.slice(0, 50), center)
    setStage('map', 2)
  }

  function clearSearch() {
    setSearchText('')
    search.close()
  }
  const mapMoving = useSheetStore((s) => s.mapMoving)
  const setMapMoving = useSheetStore((s) => s.setMapMoving)
  const modalOpen = useSheetStore((s) => s.modalOpen)
  const setModalOpen = useSheetStore((s) => s.setModalOpen)
  const controller = useRef<MapController | null>(null)
  const [activeControl, setActiveControl] = useState<ControlKey | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const panelBack = usePanelBackStore((s) => s.back)

  // 검색은 지도 하나 안의 잠깐 작업이다. 지도를 떠나면(다른 지도로 바꿔도) 닫는다 — 다음 지도에 이전 검색 결과가 남지 않게.
  useEffect(() => () => useSearchStore.getState().close(), [])

  const openProfile = (open: boolean) => {
    setProfileOpen(open)
    setModalOpen(open)
  }

  // 주소로 바로 연 핀(새로고침·공유 링크)은 지도가 뜬 뒤에야 옮길 수 있어서, 준비됐다는 걸 state 로도 둔다.
  const [mapReady, setMapReady] = useState(false)
  const onMapReady = useCallback((c: MapController) => {
    controller.current = c
    setMapReady(true)
  }, [])

  // 핀을 고르면(?pin=) 지도가 그 핀으로 간다(#843). 목록·지도 핀·검색 결과·확정 탭 어디서 골랐든 여기 한 곳이다.
  // 검색 결과·AI 후보는 핀이 아니라 아래 effect 가 같은 focusPin 을 부른다.
  // 같은 핀으로 목록이 다시 와도(실시간·의견 등록) 다시 옮기지 않는다. 고르기를 풀면 지도는 그대로 둔다.
  const focusedPinId = useRef<string | null>(null)
  useEffect(() => {
    if (!selectedPinId) {
      focusedPinId.current = null
      return
    }
    if (!mapReady || focusedPinId.current === selectedPinId) return
    const pin = allPins.find((p) => p.id === selectedPinId)
    // 자리가 아직 없는 핀(실시간 핀 해석 전)은 자리가 생기면 그때 옮긴다.
    if (!pin || !isPlaced(pin)) return
    focusedPinId.current = selectedPinId
    controller.current?.focusPin(pin.lat, pin.lng)
  }, [selectedPinId, allPins, mapReady])

  // 결과가 오면 결과 전체가, 하나를 고르면 그 장소가 보이게 지도를 옮긴다.
  useEffect(() => {
    if (found?.length) controller.current?.fitPins(found)
  }, [found])
  useEffect(() => {
    const r = found?.find((f) => f.place_id === search.selectedId)
    if (r) controller.current?.focusPin(r.lat, r.lng)
  }, [found, search.selectedId])

  // AI 후보를 고르면(카드·지도 점선 핀) 그 후보로 간다(#843). 올린 후보는 그 자리의 핀으로 간다.
  // 결과를 다시 받아도 같은 선택이면 다시 옮기지 않는다.
  const focusedCandidate = useRef<typeof candidateFocus>(null)
  useEffect(() => {
    if (!candidateFocus || !mapReady || focusedCandidate.current === candidateFocus) return
    const c = result?.candidates.find((r) => r.id === candidateFocus.id)
    if (c?.lat == null || c.lng == null) return
    focusedCandidate.current = candidateFocus
    controller.current?.focusPin(c.lat, c.lng)
  }, [candidateFocus, result, mapReady])

  // 추천 결과가 오면(첫 추천·다시 추천·반경 넓히기마다 한 번) 후보 전체가 보이게 지도를 맞춘다. 올린 후보도 이번 결과라 같이 넣는다.
  // 같은 결과를 다시 받거나(게시·새로고침) 탭을 오가도 다시 옮기지 않는다 — 사람이 옮겨 둔 지도를 뺏지 않게.
  const fittedResult = useRef<string | null>(null)
  useEffect(() => {
    if (!onRecommendTab || !mapReady || !run || run.status !== 'done' || !result) return
    const key = `${run.id}-${run.attempt_no}-${run.default_radius_walk_min ?? 0}`
    if (fittedResult.current === key) return
    const points = result.candidates.flatMap((c) => (c.lat == null || c.lng == null ? [] : [{ lat: c.lat, lng: c.lng }]))
    if (!points.length) return
    fittedResult.current = key
    controller.current?.fitPins(points)
  }, [onRecommendTab, mapReady, run, result])

  // 지도 빈 곳을 누르면 고른 것을 푼다 — 핀 상세(마킹·확정 탭)는 목록으로, 검색은 결과 목록으로, AI 후보는 강조만 푼다.
  // 지도는 그대로 둔다. 푼 게 없으면(마킹 탭) 누른 자리 근처의 핀으로 만들 수 있는 장소를 찾는다(#486).
  function onMapClick(at: { lat: number; lng: number } | null) {
    const search = useSearchStore.getState()
    const ai = useAiStore.getState()
    const released = Boolean(selectedPinId || search.selectedId || ai.focus)
    if (selectedPinId) selectPin(null)
    if (search.selectedId) search.select(null)
    if (ai.focus) ai.blurCandidate()
    if (released || !at || !onMarkingTab) return
    search.openTap(at)
    setStage('map', 2)
    // 접힌 패널에선 결과를 볼 곳이 없다(넓은 화면).
    useSheetStore.getState().setPanelOpen(true)
  }

  const onMovingChange = useCallback(
    (moving: boolean) => {
      setMapMoving(moving)
      // 사용자가 지도를 직접 옮기면 "최근 핀·전체 핀을 보는 중" 표시는 더 맞지 않다.
      if (moving) setActiveControl(null)
    },
    [setMapMoving],
  )

  function onControl(key: ControlKey) {
    const map = controller.current
    if (!map) return showToast('지도가 아직 준비되지 않았어요')
    // 최근 핀은 필터와 상관없이 지도 전체에서, 전체 핀 보기는 지금 보이는(필터된) 핀으로.
    const placed = (key === 'recent' ? allPins : pins).filter(isPlaced)

    if (key === 'locate') {
      if (!navigator.geolocation) return showToast('이 브라우저는 현재 위치를 지원하지 않아요')
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          map.panTo(pos.coords.latitude, pos.coords.longitude)
          setActiveControl('locate')
        },
        (err) =>
          showToast(
            err.code === err.PERMISSION_DENIED
              ? '위치 권한이 꺼져 있어요. 브라우저 설정에서 켜 주세요'
              : '현재 위치를 찾지 못했어요',
          ),
      )
      return
    }
    if (placed.length === 0) return showToast(pins.length < allPins.length ? '필터에 걸리는 핀이 없어요' : '아직 지도에 핀이 없어요')
    if (key === 'recent') {
      const pin = [...placed].sort(byNewest)[0]
      map.panTo(pin.lat!, pin.lng!)
      const who = [pin.created_by_display_name, timeAgo(pin.created_at)].filter(Boolean).join(' · ')
      showToast(`가장 최근 핀 · ${pin.place_name ?? '이름 없는 핀'} (${who})`)
    } else {
      map.fitPins(placed)
      showToast(`핀 ${placed.length}곳을 모두 보여 줘요`)
    }
    setActiveControl(key)
  }

  const context: ShellContext = { mapId, activeControl, onControl, connection, getCenter: () => controller.current?.getCenter() ?? null }
  // 3단계에서는 칩이 시트 제목 아래로 옮겨 간다(MapTab). 넓은 화면엔 단계가 없다. 검색 중에는 숨긴다(Figma 규칙).
  const chipsShown = onMarkingTab && (desktop || markingStage !== 3) && !search.source
  const fade = mapMoving ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
  // 패널이 다 열려 자리 잡았는지. 접기 시작하면 바로 false, 펼치면 미끄러지기가 끝난 뒤 true.
  // - 지도 틀은 이때만 좁힌다. 그래야 패널이 미끄러지는 동안 그 뒤에 늘 지도가 깔려 있다
  //   (지도 틀을 같이 움직이면 카카오맵이 프레임마다 다시 재지 못해 회색이 비친다).
  // - 탭 줄은 이때만 패널 아래로 내린다(TabRail).
  const [panelSettled, setPanelSettled] = useState(panelOpen)
  if (!panelOpen && panelSettled) setPanelSettled(false)
  useEffect(() => {
    if (!panelOpen) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const t = window.setTimeout(() => setPanelSettled(true), reduce ? 0 : PANEL_SLIDE_MS)
    return () => window.clearTimeout(t)
  }, [panelOpen])
  // 넓은 화면의 지도 영역 왼쪽 끝 — 패널을 접어도 탭 줄은 남는다.
  const mapLeft = desktop ? (panelSettled ? panelW : RAIL_W) : 0
  // 지도 위 덧칠(칩·« 손잡이)은 패널 가장자리를 따라 같이 미끄러진다.
  const overlayLeft = panelOpen ? panelW : RAIL_W

  return (
    <>
      <MapCanvas
        pins={pins}
        selectedPinId={selectedPinId}
        memberCount={memberCount}
        results={searchMarkers}
        candidates={candidates}
        route={routeDrawings}
        // 확정 탭에서 누른 핀은 확정 탭 안에서 연다(「‹ 확정된 장소」로 돌아온다).
        onSelect={(pinId) => {
          setPanelOpen(true)
          // 검색 결과를 보다가 핀을 고르면 매달린 핑고는 들어간다.
          useSearchStore.getState().select(null)
          navigate(`/maps/${mapId}${onShortlistTab ? '/shortlist' : ''}?pin=${encodeURIComponent(pinId)}`)
        }}
        onReady={onMapReady}
        onMovingChange={onMovingChange}
        onMapClick={onMapClick}
        leftInset={mapLeft}
      />

      {desktop && <TabRail mapId={mapId} raised={!panelSettled} />}

      {/* 모바일은 'contents' 라 틀이 없고 안쪽이 각자 화면에 붙는다. 넓은 화면은 이 틀이 탭 줄 오른쪽 내용 패널이다. */}
      {/* 접기는 탭 줄 뒤로 left 를 옮겨 미끄러뜨린다 — transform 이면 안쪽 fixed 확인 창이 패널 기준으로 잡힌다. */}
      {/* 다 접히면 invisible + inert 로 보이지도, 포커스가 들어가지도 않는다. */}
      <div
        id="map-panel"
        inert={desktop && !panelOpen}
        style={desktop ? { left: panelOpen ? RAIL_W : RAIL_W - (panelW - RAIL_W), width: panelW - RAIL_W } : undefined}
        className={
          desktop
            ? `fixed inset-y-0 z-30 flex flex-col border-r border-ink-200 bg-white transition-[left,visibility] duration-300 ease-out motion-reduce:transition-none ${
                panelOpen ? 'visible' : 'invisible'
              }`
            : 'contents'
        }
      >
        {/* 넓은 화면 pb-1: 검색창 포커스 테두리(바깥 4px)가 바로 아래 탭 내용(흰 바탕)에 덮이지 않게 자리를 둔다. */}
        <header
          data-map-header
          className={desktop ? 'shrink-0 space-y-3 px-4 pb-1 pt-3' : 'pointer-events-none fixed inset-x-0 top-0 z-20 space-y-2 px-4 pt-3'}
        >
          <div className={desktop ? 'flex items-center gap-2' : 'flex items-center justify-between'}>
            {desktop ? (
              // 넓은 화면의 ‹ 는 패널 안 이전 화면(핀 상세 → 목록 등)이다. 돌아갈 곳이 없으면 없다 — 지도 밖으로는 제목 메뉴로 나간다.
              panelBack && (
                <button
                  type="button"
                  onClick={panelBack.onBack}
                  aria-label={backAriaLabel(panelBack.label)}
                  title={`‹ ${panelBack.label}`}
                  className="hit-44 flex size-8 shrink-0 items-center justify-center rounded-full text-ink-900 hover:bg-ink-100"
                >
                  <ChevronLeft size={20} />
                </button>
              )
            ) : (
              <Link
                to="/"
                aria-label="내 지도 목록으로"
                className="pointer-events-auto hit-44 flex size-8 items-center justify-center rounded-full bg-white text-ink-900 shadow-float"
              >
                <ChevronLeft size={20} />
              </Link>
            )}
            {/* 넓은 화면은 지도 위가 아니라 자리가 있어서 지도 제목을 같이 둔다(#338). 제목을 누르면 다른 지도로 바로 옮긴다. */}
            {/* 제목이 메뉴 버튼이 돼도 화면 제목(h1)은 남긴다 — 스크린리더가 제목으로 찾아간다. */}
            {desktop && (
              <h1 className="flex min-w-0 flex-1">
                <MapSwitcher mapId={mapId} title={mapInfo?.title} />
              </h1>
            )}
            {/* 내 이니셜 원은 계정 버튼처럼 읽혀서, 구성원 아이콘 + 인원 수로 "이 지도의 정보·구성원"임을 보인다(#351). */}
            {/* 넓은 화면은 바닥 시트 대신 버튼 아래 메뉴로 연다 — 패널 옆 바닥 시트는 끌리지도 않는 손잡이만 남았다. */}
            {/* 알림함(#483) — 다른 지도의 알림도 여기서 본다. */}
            {desktop && <NotificationBell />}
            {desktop ? (
              <ProfileMenu
                mapId={mapId}
                trigger={
                  <button
                    type="button"
                    aria-label={`지도 정보와 구성원 · ${memberCount}명`}
                    className="hit-44 flex h-8 shrink-0 items-center gap-1 rounded-full border border-ink-200 bg-white px-2.5 text-sm font-bold text-brand-600 hover:bg-ink-50 data-[state=open]:border-brand-600 data-[state=open]:bg-brand-50"
                  >
                    <Users size={16} aria-hidden="true" />
                    {memberCount > 0 && memberCount}
                  </button>
                }
              />
            ) : (
              <div className="flex items-center gap-3">
                <NotificationBell floating />
                <button
                  type="button"
                  aria-label={`지도 정보와 구성원 · ${memberCount}명`}
                  onClick={() => openProfile(true)}
                  className="pointer-events-auto hit-44 flex h-8 items-center gap-1 rounded-full bg-white px-2.5 text-sm font-bold text-brand-600 shadow-float"
                >
                  <Users size={16} aria-hidden="true" />
                  {memberCount > 0 && memberCount}
                </button>
              </div>
            )}
          </div>
          {/* 지도 위에는 검색창만 둔다(FE 회의). 지도를 끄는 동안엔 지도에 집중하게 흐려진다. 검색 동작은 #293. */}
          {/* 검색 결과는 화면에 보여 주기만 한다(#53). Enter 나 돋보기를 눌렀을 때만 부른다(호출 상한, api-spec). */}
          {/* 넓은 화면은 패널 안이라 그림자·흐림이 없다(그림자는 지도 위에 떠 있는 것에만). */}
          <form
            role="search"
            inert={!desktop && mapMoving}
            onSubmit={submitSearch}
            className={`${desktop ? '' : 'pointer-events-auto '}flex items-center gap-2 rounded-xl border bg-white px-4 py-3 ${desktop ? '' : 'shadow-float transition-opacity '}has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-[var(--line-focus)] ${
              search.source ? 'border-brand-600' : 'border-ink-200'
            }${desktop ? '' : ` ${fade}`}`}
          >
            <input
              id="place-search"
              type="search"
              enterKeyHint="search"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              maxLength={2000}
              placeholder="장소 이름 또는 지도 링크"
              aria-label="장소 검색"
              className="min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-ink-500 [&::-webkit-search-cancel-button]:hidden"
            />
            {searchText && <ClearButton label="검색어 지우기" onClick={clearSearch} />}
            <button type="submit" aria-label="검색" className="hit-44 text-brand-600">
              <Search size={20} />
            </button>
          </form>
          {!desktop && chipsShown && (
            <CategoryChips
              value={filters.category}
              onChange={(c) => setFilter('category', c)}
              floating
              className={`pointer-events-auto -mx-4 px-4 pb-1 transition-opacity ${fade}`}
            />
          )}
        </header>

        <Outlet context={context} />

        {!desktop && (
          <nav
            style={{ minHeight: `calc(${TAB_BAR_H}px + env(safe-area-inset-bottom, 0px))` }}
            className="pb-safe fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 items-end border-t border-ink-100 bg-white"
          >
            {TABS.map((tab) =>
              tab.Icon ? (
                <TabLink key={tab.path} to={`/maps/${mapId}${tab.path}`} end={tab.end} label={tab.label} icon={<tab.Icon size={24} />} />
              ) : (
                <AiTabLink key={tab.path} to={`/maps/${mapId}${tab.path}`} label={tab.label} />
              ),
            )}
          </nav>
        )}
      </div>

      {/* 넓은 화면의 지도 영역 위. 지도를 끌 수 있게 누름은 통과시키고, 올린 것들만 다시 받는다. */}
      {desktop && (
        <div
          className="pointer-events-none fixed inset-y-0 right-0 z-20 transition-[left] duration-300 ease-out motion-reduce:transition-none"
          style={{ left: overlayLeft }}
        >
          <div className="absolute inset-x-4 top-3 flex flex-col items-start gap-2">
            {chipsShown && (
              <CategoryChips
                value={filters.category}
                onChange={(c) => setFilter('category', c)}
                floating
                // 마우스로는 옆으로 밀기 어렵고 가로 스크롤바가 지도를 가려서, 좁으면 줄을 바꾼다.
                // 터치(태블릿)는 모바일처럼 옆으로 민다 — 좁은 지도 위에서 칩이 두세 줄로 쌓이지 않게(#603).
                className={`pointer-events-auto max-w-full pointer-fine:flex-wrap transition-opacity ${fade}`}
              />
            )}
            {connection.state !== 'open' && <ConnectionBanner floating state={connection.state} onReconnect={connection.reconnect} />}
          </div>
          <PanelToggle open={panelOpen} onToggle={() => setPanelOpen(!panelOpen)} />
          <MapControls docked hidden={modalOpen} fading={mapMoving} active={activeControl} onPress={onControl} />
          {onMarkingTab && <AgentButton docked mapId={mapId} hidden={modalOpen} fading={mapMoving} />}
          {!modalOpen && <Toaster docked controlsVisible={!mapMoving} />}
        </div>
      )}

      {profileOpen && !desktop && <ProfileModal mapId={mapId} onClose={() => openProfile(false)} />}
    </>
  )
}

/**
 * 최종기획안 4절 — 탭은 이 3개로 고정, 라벨도 고정 용어(9절). 하단 탭과 넓은 화면 탭 줄이 이 표 하나를 쓴다.
 * AI 는 선 아이콘 대신 핑고 얼굴(PingoMark)이다(Icon 없음).
 */
const TABS: { path: string; end?: boolean; label: string; Icon: LucideIcon | null }[] = [
  { path: '', end: true, label: '마킹된 장소', Icon: MapPin },
  { path: '/recommend', label: 'AI 추천', Icon: null },
  { path: '/shortlist', label: '확정된 장소', Icon: FileText },
]

/** 비활성 #6B7181(흰 바탕 대비 약 5:1). */
function TabLink({ to, end, label, icon }: { to: string; end?: boolean; label: string; icon: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `flex flex-col items-center gap-0.5 pb-2 text-label font-medium ${isActive ? 'text-brand-600' : 'text-ink-500'}`
      }
    >
      {icon}
      {label}
    </NavLink>
  )
}

/** 하단 탭의 AI. 늘 채운 파랑이면 화면마다 채움 덩어리가 하나 더 생겨서, 비활성은 흰 원 + 파란 핑고 얼굴, 활성만 파랑 채움 + 흰 얼굴(#299). */
function AiTabLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex flex-col items-center gap-0.5 pb-2 text-label font-medium ${isActive ? 'text-brand-600' : 'text-ink-500'}`
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={`flex size-12 items-center justify-center rounded-full shadow-float ${
              isActive ? 'bg-brand-600' : 'border-2 border-brand-300 bg-white'
            }`}
          >
            <PingoMark size={30} tone={isActive ? 'white' : 'blue'} />
          </span>
          {label}
        </>
      )}
    </NavLink>
  )
}

/**
 * 넓은 화면 왼쪽 끝 세로 탭 줄(#338, 네이버 지도처럼). 라벨·아이콘은 하단 탭과 같고 AI 도 다른 탭과 같은 모양이다.
 * 패널을 접어도 남고, 누르면 그 탭으로 가면서 패널을 다시 연다.
 */
function TabRail({ mapId, raised }: { mapId: string; raised: boolean }) {
  // 패널이 다 열려 있으면 탭 줄은 패널(z-30)보다 아래 — 패널 안 확인 창의 딤이 DOM 순서와 상관없이 탭 줄까지 덮는다.
  // 미끄러지는 중이거나 접혀 있으면(raised) 위 — 패널이 탭 줄 밑으로 들어가고 나온다. 확인 창은 다 열린 패널에서만 뜬다.
  return (
    <nav
      aria-label="지도 탭"
      style={{ width: RAIL_W }}
      className={`fixed inset-y-0 left-0 ${raised ? 'z-40' : 'z-20'} flex flex-col gap-1 border-r border-ink-200 bg-white px-1 pt-3`}
    >
      {TABS.map((tab) => (
        <RailTab
          key={tab.path}
          to={`/maps/${mapId}${tab.path}`}
          end={tab.end}
          label={tab.label}
          icon={tab.Icon ? <tab.Icon size={24} /> : <PingoMark size={28} />}
        />
      ))}
    </nav>
  )
}

/**
 * 탭 줄의 칸 하나. 아이콘 + 11/500 라벨(하단 탭과 같은 위계), 활성은 brand-50 면 + brand-600.
 * 지금 탭을 다시 누르면 이동하지 않고 패널만 연다 — 이동하면 보던 핀 상세(?pin=)가 사라진다.
 */
function RailTab({ to, end = false, label, icon }: { to: string; end?: boolean; label: string; icon: ReactNode }) {
  const active = useMatch({ path: to, end }) !== null
  const panelOpen = useSheetStore((s) => s.panelOpen)
  return (
    <NavLink
      to={to}
      end={end}
      aria-controls="map-panel"
      aria-expanded={panelOpen}
      onClick={(e) => {
        if (active) e.preventDefault()
        useSheetStore.getState().setPanelOpen(true)
      }}
      className={({ isActive }) =>
        `flex flex-col items-center gap-1 rounded-xl py-2.5 text-label font-medium break-keep ${
          isActive ? 'bg-brand-50 text-brand-600' : 'text-ink-500 hover:bg-ink-50 hover:text-ink-700'
        }`
      }
    >
      {/* 핑고는 선 아이콘보다 커서 같은 칸에 넣어 세 칸 높이를 맞춘다. */}
      <span className="flex size-7 items-center justify-center">{icon}</span>
      {label}
    </NavLink>
  )
}

/**
 * 패널 접기·펼치기 손잡이(#338). 지도 영역 왼쪽 끝(펼치면 패널, 접으면 탭 줄 오른쪽) 세로 가운데에 붙는다.
 * 보이는 건 24×48, 누르는 곳은 44×56.
 */
function PanelToggle({ open, onToggle }: { open: boolean; onToggle: () => void }) {
  return (
    <button
      type="button"
      aria-label={open ? '패널 접기' : '패널 펼치기'}
      aria-expanded={open}
      aria-controls="map-panel"
      onClick={onToggle}
      className="pointer-events-auto absolute left-0 top-1/2 flex h-14 w-11 -translate-y-1/2 items-center"
    >
      <span className="flex h-12 w-6 items-center justify-center rounded-r-lg border border-l-0 border-ink-200 bg-white text-ink-600 shadow-float">
        {open ? <ChevronsLeft size={16} aria-hidden="true" /> : <ChevronsRight size={16} aria-hidden="true" />}
      </span>
    </button>
  )
}
