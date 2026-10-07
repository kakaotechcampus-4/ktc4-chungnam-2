import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useMatch, useNavigate, useParams } from 'react-router'
import { ChevronLeft, ChevronsLeft, ChevronsRight, FileText, MapPin, Search, Users, X, type LucideIcon } from 'lucide-react'

import MapCanvas, { type MapController } from '@/features/map/MapCanvas'
import { usePinSelection } from '@/features/map/usePinSelection'
import { byNewest, filterPins, isPlaced, timeAgo } from '@/features/map/model'
import { CategoryChips } from '@/features/map/PinFilterControls'
import { useLivePinResolver } from '@/features/map/livePlaces'
import { usePinsQuery } from '@/features/map/queries'
import { useMapEvents } from '@/features/map/realtime'
import { usePinFilters } from '@/features/map/usePinFilters'
import { useMapQuery } from '@/features/maps/queries'
import { usePlaceSearchQuery } from '@/features/search/queries'
import { toRouteDrawings } from '@/features/shortlist/model'
import { useRouteQuery } from '@/features/shortlist/queries'
import { useRouteStore } from '@/features/shortlist/routeStore'
import { useSearchStore } from '@/features/search/searchStore'
import { PANEL_W, RAIL_W, TAB_BAR_H } from '@/features/shell/layout'
import MapControls, { type ControlKey } from '@/features/shell/MapControls'
import ProfileModal from '@/features/shell/ProfileModal'
import { useSheetStore } from '@/features/shell/sheetStore'
import type { ShellContext } from '@/features/shell/shellContext'
import { ConnectionBanner } from '@/features/shell/TabSheet'
import { showToast } from '@/features/shell/toast'
import Toaster from '@/features/shell/Toaster'
import { useIsDesktop } from '@/features/shell/useIsDesktop'
import Pingo from '@/ui/Pingo'

/**
 * 지도 하나 안의 화면(최종기획안 4절). 지도는 항상 떠 있고, 하단 탭 3개가 그 위 바텀시트 내용을 바꾼다.
 * 지도는 여기 한 번만 만든다 — 탭마다 만들면 탭을 바꿀 때마다 지도가 다시 뜬다.
 *
 * 넓은 화면(768px 이상, #338)은 왼쪽 480px(세로 탭 줄 72 + 높이 전체 내용 패널 408: 헤더·검색·탭 내용) + 오른쪽 지도 영역이다.
 * 칩·연결 띠·지도 버튼·토스트는 지도 영역에 둔다. 패널과 모바일은 같은 트리를 쓰고 틀의 클래스만 바꾼다 —
 * 768px 경계를 넘나들어도 탭 내용(쓰던 의견 등)이 다시 마운트되지 않게.
 */
export default function MapLayout() {
  const { mapId = '' } = useParams()
  const navigate = useNavigate()
  const { selectedPinId } = usePinSelection()
  const { data: allPins = [] } = usePinsQuery(mapId)
  const mapInfo = useMapQuery(mapId).data
  const memberCount = mapInfo?.memberCount ?? 0
  useLivePinResolver(allPins, mapInfo?.regionCenter)
  const desktop = useIsDesktop()
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
  const routeDrawings = useMemo(() => (routeOn && routes ? toRouteDrawings(routes, allPins) : []), [routeOn, routes, allPins])
  const markingStage = useSheetStore((s) => s.stages.map)
  const setStage = useSheetStore((s) => s.setStage)
  const search = useSearchStore()
  const [searchText, setSearchText] = useState('')
  // 결과 시트에서 「닫기」를 눌러도 입력칸에 글자가 남지 않게, 검색이 닫히면 같이 비운다(#351).
  const [lastQuery, setLastQuery] = useState(search.query)
  if (lastQuery !== search.query) {
    setLastQuery(search.query)
    if (search.query === null) setSearchText('')
  }
  const found = usePlaceSearchQuery(search.query, search.near).data
  // 검색 결과 번호 원 — 결과나 선택이 바뀔 때만 다시 그린다.
  const searchMarkers = useMemo(
    () =>
      (found ?? []).map((r, i) => ({
        n: i + 1,
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

  function submitSearch(e: React.FormEvent) {
    e.preventDefault()
    const q = searchText.trim()
    if (!q) return
    // 검색은 마킹 탭의 일이다. 다른 탭에서 검색해도 마킹 탭으로 가서 결과를 보여준다.
    if (!onMarkingTab) navigate(`/maps/${mapId}`)
    search.submit(q.slice(0, 50), controller.current?.getCenter() ?? null)
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

  const openProfile = (open: boolean) => {
    setProfileOpen(open)
    setModalOpen(open)
  }

  const onMapReady = useCallback((c: MapController) => {
    controller.current = c
  }, [])

  // 결과가 오면 결과 전체가, 하나를 고르면 그 장소가 보이게 지도를 옮긴다.
  useEffect(() => {
    if (found?.length) controller.current?.fitPins(found)
  }, [found])
  useEffect(() => {
    const r = found?.find((f) => f.place_id === search.selectedId)
    if (r) controller.current?.panTo(r.lat, r.lng)
  }, [found, search.selectedId])

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

  const context: ShellContext = { mapId, activeControl, onControl, connection }
  // 3단계에서는 칩이 시트 제목 아래로 옮겨 간다(MapTab). 넓은 화면엔 단계가 없다. 검색 중에는 숨긴다(Figma 규칙).
  const chipsShown = onMarkingTab && (desktop || markingStage !== 3) && !search.query
  const fade = mapMoving ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
  // 넓은 화면의 지도 영역 왼쪽 끝 — 패널을 접어도 탭 줄은 남는다.
  const mapLeft = desktop ? (panelOpen ? PANEL_W : RAIL_W) : 0

  return (
    <>
      <MapCanvas
        pins={pins}
        selectedPinId={selectedPinId}
        memberCount={memberCount}
        results={searchMarkers}
        route={routeDrawings}
        // 확정 탭에서 누른 핀은 확정 탭 안에서 연다(「‹ 확정된 장소」로 돌아온다).
        onSelect={(pinId) => {
          setPanelOpen(true)
          navigate(`/maps/${mapId}${onShortlistTab ? '/shortlist' : ''}?pin=${encodeURIComponent(pinId)}`)
        }}
        onReady={onMapReady}
        onMovingChange={onMovingChange}
        leftInset={mapLeft}
      />

      {desktop && <TabRail mapId={mapId} />}

      {/* 모바일은 'contents' 라 틀이 없고 안쪽이 각자 화면에 붙는다. 넓은 화면은 이 틀이 탭 줄 오른쪽 내용 패널이다. */}
      {/* 접기는 transform 대신 hidden — transform 이면 안쪽 fixed 확인 창이 패널 기준으로 잡힌다. */}
      <div
        id="map-panel"
        hidden={desktop && !panelOpen}
        style={desktop ? { left: RAIL_W, width: PANEL_W - RAIL_W } : undefined}
        className={desktop ? 'fixed inset-y-0 z-30 flex flex-col border-r border-ink-200 bg-white' : 'contents'}
      >
        <header
          data-map-header
          className={desktop ? 'shrink-0 space-y-3 px-4 pt-3' : 'pointer-events-none fixed inset-x-0 top-0 z-20 space-y-2 px-4 pt-3'}
        >
          <div className={desktop ? 'flex items-center gap-2' : 'flex items-center justify-between'}>
            <Link
              to="/"
              aria-label="내 지도 목록으로"
              className={
                desktop
                  ? 'hit-44 flex size-8 shrink-0 items-center justify-center rounded-full text-ink-900 hover:bg-ink-100'
                  : 'pointer-events-auto hit-44 flex size-8 items-center justify-center rounded-full bg-white text-ink-900 shadow-md'
              }
            >
              <ChevronLeft size={20} />
            </Link>
            {/* 넓은 화면은 지도 위가 아니라 자리가 있어서 지도 제목을 같이 둔다(#338 목표 레이아웃). */}
            {desktop && <h1 className="min-w-0 flex-1 truncate text-[1.0625rem] font-bold text-ink-900">{mapInfo?.title}</h1>}
            {/* 내 이니셜 원은 계정 버튼처럼 읽혀서, 구성원 아이콘 + 인원 수로 "이 지도의 정보·구성원"임을 보인다(#351). */}
            <button
              type="button"
              aria-label={`지도 정보와 구성원 · ${memberCount}명`}
              onClick={() => openProfile(true)}
              className={
                desktop
                  ? 'hit-44 flex h-8 shrink-0 items-center gap-1 rounded-full border border-ink-200 bg-white px-2.5 text-sm font-bold text-brand-600'
                  : 'pointer-events-auto hit-44 flex h-8 items-center gap-1 rounded-full bg-white px-2.5 text-sm font-bold text-brand-600 shadow-md'
              }
            >
              <Users size={16} aria-hidden="true" />
              {memberCount > 0 && memberCount}
            </button>
          </div>
          {/* 지도 위에는 검색창만 둔다(FE 회의). 지도를 끄는 동안엔 지도에 집중하게 흐려진다. 검색 동작은 #293. */}
          {/* 검색 결과는 화면에 보여 주기만 한다(#53). Enter 나 돋보기를 눌렀을 때만 부른다(호출 상한, api-spec). */}
          {/* 넓은 화면은 패널 안이라 그림자·흐림이 없다(그림자는 지도 위에 떠 있는 것에만). */}
          <form
            role="search"
            inert={!desktop && mapMoving}
            onSubmit={submitSearch}
            className={`${desktop ? '' : 'pointer-events-auto '}flex items-center gap-2 rounded-xl border bg-white px-4 py-3 ${desktop ? '' : 'shadow-md transition-opacity '}has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-[var(--line-focus)] ${
              search.query ? 'border-brand-600' : 'border-ink-200'
            }${desktop ? '' : ` ${fade}`}`}
          >
            <input
              id="place-search"
              type="search"
              enterKeyHint="search"
              value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              maxLength={50}
              placeholder="장소 검색하기"
              aria-label="장소 검색"
              className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-500 [&::-webkit-search-cancel-button]:hidden"
            />
            {searchText && (
              <button type="button" aria-label="검색어 지우기" onClick={clearSearch} className="hit-44 flex size-5 items-center justify-center rounded-full bg-ink-300 text-white">
                <X size={12} />
              </button>
            )}
            <button type="submit" aria-label="검색" className="hit-44 text-brand-600">
              <Search size={20} />
            </button>
          </form>
          {!desktop && chipsShown && (
            <CategoryChips
              value={filters.category}
              onChange={(c) => setFilter('category', c)}
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
        <div className="pointer-events-none fixed inset-y-0 right-0 z-20" style={{ left: mapLeft }}>
          <div className="absolute inset-x-4 top-3 flex flex-col items-start gap-2">
            {chipsShown && (
              <CategoryChips
                value={filters.category}
                onChange={(c) => setFilter('category', c)}
                // 마우스로는 옆으로 밀기 어렵고 가로 스크롤바가 지도를 가려서, 좁으면 줄을 바꾼다.
                className={`pointer-events-auto max-w-full flex-wrap transition-opacity ${fade}`}
              />
            )}
            {connection.state !== 'open' && <ConnectionBanner floating state={connection.state} onReconnect={connection.reconnect} />}
          </div>
          <PanelToggle open={panelOpen} onToggle={() => setPanelOpen(!panelOpen)} />
          <MapControls docked hidden={modalOpen} fading={mapMoving} active={activeControl} onPress={onControl} />
          {!modalOpen && <Toaster docked controlsVisible={!mapMoving} />}
        </div>
      )}

      {profileOpen && <ProfileModal mapId={mapId} onClose={() => openProfile(false)} />}
    </>
  )
}

/**
 * 최종기획안 4절 — 탭은 이 3개로 고정, 라벨도 고정 용어(9절). 하단 탭과 넓은 화면 탭 줄이 이 표 하나를 쓴다.
 * AI 는 선 아이콘 대신 핑고가 말한다(Icon 없음).
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
        `flex flex-col items-center gap-0.5 pb-2 text-[0.6875rem] font-medium ${isActive ? 'text-brand-600' : 'text-ink-500'}`
      }
    >
      {icon}
      {label}
    </NavLink>
  )
}

/** 하단 탭의 AI. 늘 채운 파랑이면 화면마다 채움 덩어리가 하나 더 생겨서, 비활성은 흰 원 + 핑고, 활성만 파랑 채움 + 흰 핑고(#299). */
function AiTabLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex flex-col items-center gap-0.5 pb-2 text-[0.6875rem] font-medium ${isActive ? 'text-brand-600' : 'text-ink-500'}`
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={`flex size-12 items-center justify-center rounded-full shadow-md ${
              isActive ? 'bg-brand-600' : 'border-2 border-brand-300 bg-white'
            }`}
          >
            <Pingo size={30} onFill={isActive} />
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
function TabRail({ mapId }: { mapId: string }) {
  // 탭 줄은 패널(z-30)보다 아래 — 패널 안 확인 창의 딤이 DOM 순서와 상관없이 탭 줄까지 덮는다.
  return (
    <nav aria-label="지도 탭" style={{ width: RAIL_W }} className="fixed inset-y-0 left-0 z-20 flex flex-col gap-1 border-r border-ink-200 bg-white px-1 pt-3">
      {TABS.map((tab) => (
        <RailTab
          key={tab.path}
          to={`/maps/${mapId}${tab.path}`}
          end={tab.end}
          label={tab.label}
          icon={tab.Icon ? <tab.Icon size={22} /> : <Pingo size={26} />}
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
        `flex flex-col items-center gap-1 rounded-xl py-2.5 text-[0.6875rem] font-medium break-keep ${
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
      <span className="flex h-12 w-6 items-center justify-center rounded-r-lg border border-l-0 border-ink-200 bg-white text-ink-600 shadow-md">
        {open ? <ChevronsLeft size={16} aria-hidden="true" /> : <ChevronsRight size={16} aria-hidden="true" />}
      </span>
    </button>
  )
}
