import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useMatch, useNavigate, useParams } from 'react-router'
import { ChevronLeft, FileText, MapPin, Search, X } from 'lucide-react'

import { useMeQuery } from '@/features/auth/queries'
import MapCanvas, { type MapController } from '@/features/map/MapCanvas'
import { usePinSelection } from '@/features/map/usePinSelection'
import { filterPins } from '@/features/map/model'
import { CategoryChips } from '@/features/map/PinFilterControls'
import { usePinsQuery } from '@/features/map/queries'
import { useMapEvents } from '@/features/map/realtime'
import { usePinFilters } from '@/features/map/usePinFilters'
import { useMapQuery } from '@/features/maps/queries'
import { usePlaceSearchQuery } from '@/features/search/queries'
import { useSearchStore } from '@/features/search/searchStore'
import { TAB_BAR_H } from '@/features/shell/layout'
import type { ControlKey } from '@/features/shell/MapControls'
import ProfileModal from '@/features/shell/ProfileModal'
import { useSheetStore } from '@/features/shell/sheetStore'
import type { ShellContext } from '@/features/shell/shellContext'
import { showToast } from '@/features/shell/toast'
import Pingo from '@/ui/Pingo'

/**
 * 지도 하나 안의 화면(최종기획안 4절). 지도는 항상 떠 있고, 하단 탭 3개가 그 위 바텀시트 내용을 바꾼다.
 * 지도는 여기 한 번만 만든다 — 탭마다 만들면 탭을 바꿀 때마다 지도가 다시 뜬다.
 */
export default function MapLayout() {
  const { mapId = '' } = useParams()
  const navigate = useNavigate()
  const { selectedPinId } = usePinSelection()
  const { data: allPins = [] } = usePinsQuery(mapId)
  const memberCount = useMapQuery(mapId).data?.memberCount ?? 0
  const { filters, setFilter } = usePinFilters()
  // 마커와 목록이 같은 필터를 본다. 다른 탭엔 필터가 없어 전부 보인다.
  const pins = filterPins(allPins, filters)
  const connection = useMapEvents(mapId)
  const onMarkingTab = useMatch('/maps/:mapId') !== null
  const markingStage = useSheetStore((s) => s.stages.map)
  const setStage = useSheetStore((s) => s.setStage)
  const search = useSearchStore()
  const [searchText, setSearchText] = useState('')
  const found = usePlaceSearchQuery(search.query, search.near).data
  // 검색 결과 번호 원 — 결과나 선택이 바뀔 때만 다시 그린다.
  const searchMarkers = useMemo(
    () =>
      (found ?? []).map((r, i) => ({
        n: i + 1,
        lat: r.lat,
        lng: r.lng,
        selected: r.place_id === search.selectedId,
        onClick: () => useSearchStore.getState().select(r.place_id),
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
  const me = useMeQuery()
  const mapMoving = useSheetStore((s) => s.mapMoving)
  const setMapMoving = useSheetStore((s) => s.setMapMoving)
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
    const isPlaced = (p: (typeof allPins)[number]) => typeof p.lat === 'number' && typeof p.lng === 'number'
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
      // ponytail: 핀 응답에 만든 시각이 없어 목록 마지막을 최근으로 본다. created_at 이 생기면 그 값으로.
      const pin = placed[placed.length - 1]
      map.panTo(pin.lat!, pin.lng!)
      showToast(`가장 최근 핀 · ${pin.place_name ?? '이름 없는 핀'}${pin.created_by_display_name ? ` (${pin.created_by_display_name})` : ''}`)
    } else {
      map.fitPins(placed)
      showToast(`핀 ${placed.length}곳을 모두 보여 줘요`)
    }
    setActiveControl(key)
  }

  const context: ShellContext = { mapId, activeControl, onControl, connection }

  return (
    <>
      <MapCanvas
        pins={pins}
        selectedPinId={selectedPinId}
        memberCount={memberCount}
        results={searchMarkers}
        onSelect={(pinId) => navigate(`/maps/${mapId}?pin=${encodeURIComponent(pinId)}`)}
        onReady={onMapReady}
        onMovingChange={onMovingChange}
      />

      <header data-map-header className="pointer-events-none fixed inset-x-0 top-0 z-20 space-y-2 px-4 pt-3">
        <div className="flex items-center justify-between">
          <Link
            to="/"
            aria-label="내 지도 목록으로"
            className="pointer-events-auto hit-44 flex size-8 items-center justify-center rounded-full bg-white text-ink-900 shadow-md"
          >
            <ChevronLeft size={20} />
          </Link>
          <button
            type="button"
            aria-label="지도 정보와 구성원"
            onClick={() => openProfile(true)}
            className="pointer-events-auto hit-44 flex size-8 items-center justify-center rounded-full bg-brand-600 text-sm font-semibold text-white shadow-md"
          >
            {me.data?.display_name?.slice(0, 1) ?? '나'}
          </button>
        </div>
        {/* 지도 위에는 검색창만 둔다(FE 회의). 지도를 끄는 동안엔 지도에 집중하게 흐려진다. 검색 동작은 #293. */}
        {/* 검색 결과는 화면에 보여 주기만 한다(#53). Enter 나 돋보기를 눌렀을 때만 부른다(호출 상한, api-spec). */}
        <form
          role="search"
          inert={mapMoving}
          onSubmit={submitSearch}
          className={`pointer-events-auto flex items-center gap-2 rounded-xl border bg-white px-4 py-3 shadow-md transition-opacity has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-[var(--line-focus)] ${
            search.query ? 'border-brand-600' : 'border-ink-200'
          } ${mapMoving ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'}`}
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
        {/* 3단계에서는 칩이 시트 제목 아래로 옮겨 간다(MapTab). */}
        {/* 검색 중에는 칩을 숨긴다(Figma 규칙). */}
        {onMarkingTab && markingStage !== 3 && !search.query && (
          <CategoryChips
            value={filters.category}
            onChange={(c) => setFilter('category', c)}
            className={`pointer-events-auto -mx-4 px-4 pb-1 transition-opacity ${
              mapMoving ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
            }`}
          />
        )}
      </header>

      <Outlet context={context} />

      <nav
        style={{ minHeight: `calc(${TAB_BAR_H}px + env(safe-area-inset-bottom, 0px))` }}
        className="pb-safe fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 items-end border-t border-ink-100 bg-white"
      >
        <TabLink to={`/maps/${mapId}`} end label="마킹된 장소" icon={<MapPin size={24} />} />
        {/* AI 는 핑고가 말한다. 늘 채운 파랑이면 화면마다 채움 덩어리가 하나 더 생겨서, 비활성은 흰 원 + 핑고, 활성만 파랑 채움 + 흰 핑고(#299). */}
        <NavLink
          to={`/maps/${mapId}/recommend`}
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
              AI 추천
            </>
          )}
        </NavLink>
        <TabLink to={`/maps/${mapId}/shortlist`} label="확정된 장소" icon={<FileText size={24} />} />
      </nav>

      {profileOpen && <ProfileModal mapId={mapId} onClose={() => openProfile(false)} />}
    </>
  )
}

/** 최종기획안 4절 — 탭은 이 3개로 고정, 라벨도 고정 용어(9절). 비활성 #6B7181(흰 바탕 대비 약 5:1). */
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
