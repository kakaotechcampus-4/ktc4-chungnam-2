import { useCallback, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useNavigate, useParams } from 'react-router'
import { ChevronLeft, FileText, MapPin, Search } from 'lucide-react'

import { useMeQuery } from '@/features/auth/queries'
import MapCanvas, { type MapController } from '@/features/map/MapCanvas'
import { usePinsQuery } from '@/features/map/queries'
import { TAB_BAR_H } from '@/features/shell/layout'
import type { ControlKey } from '@/features/shell/MapControls'
import ProfileModal from '@/features/shell/ProfileModal'
import { useSheetStore } from '@/features/shell/sheetStore'
import type { ShellContext } from '@/features/shell/shellContext'
import { showToast } from '@/features/shell/toast'

/**
 * 지도 하나 안의 화면(최종기획안 4절). 지도는 항상 떠 있고, 하단 탭 3개가 그 위 바텀시트 내용을 바꾼다.
 * 지도는 여기 한 번만 만든다 — 탭마다 만들면 탭을 바꿀 때마다 지도가 다시 뜬다.
 */
export default function MapLayout() {
  const { mapId = '' } = useParams()
  const navigate = useNavigate()
  const { data: pins = [] } = usePinsQuery(mapId)
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
    const placed = pins.filter((p) => typeof p.lat === 'number' && typeof p.lng === 'number')

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
    if (placed.length === 0) return showToast('아직 지도에 핀이 없어요')
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

  const context: ShellContext = { mapId, activeControl, onControl }

  return (
    <>
      <MapCanvas
        pins={pins}
        onSelect={(pinId) => navigate(`/maps/${mapId}?pin=${encodeURIComponent(pinId)}`)}
        onReady={(c) => (controller.current = c)}
        onMovingChange={onMovingChange}
      />

      <header className="pointer-events-none fixed inset-x-0 top-0 z-20 space-y-2 px-4 pt-3">
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
        {/* 사라진 동안에는 눌리지도 포커스되지도 않는다(inert). */}
        <label
          inert={mapMoving}
          className={`pointer-events-auto flex items-center gap-2 rounded-xl border border-ink-200 bg-white px-4 py-3 shadow-md transition-opacity ${
            mapMoving ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
          }`}
        >
          <input
            id="place-search"
            readOnly
            aria-label="장소 검색"
            placeholder="장소 검색하기"
            className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-ink-500"
          />
          <Search size={20} className="text-brand-600" aria-hidden="true" />
        </label>
      </header>

      <Outlet context={context} />

      <nav
        style={{ height: `calc(${TAB_BAR_H}px + env(safe-area-inset-bottom, 0px))` }}
        className="pb-safe fixed inset-x-0 bottom-0 z-40 grid grid-cols-3 items-end border-t border-ink-100 bg-white"
      >
        <TabLink to={`/maps/${mapId}`} end label="마킹된 장소" icon={<MapPin size={26} />} />
        {/* 원이 너무 크면 시트 목록 끝을 가린다. 56px로 줄이고, 활성은 안쪽 링 + 라벨 색 두 가지로 보인다 — 바깥 링은 탭 막대 위로 튀어나온다(#299). */}
        <NavLink
          to={`/maps/${mapId}/recommend`}
          className={({ isActive }) =>
            `group flex flex-col items-center gap-0.5 pb-2 text-[11px] font-medium ${isActive ? 'text-brand-600' : 'text-ink-500'}`
          }
        >
          <span className="flex size-14 items-center justify-center rounded-full bg-brand-600 text-lg font-bold text-white shadow-md ring-brand-100 ring-inset group-aria-[current=page]:ring-4">
            AI
          </span>
          AI 추천
        </NavLink>
        <TabLink to={`/maps/${mapId}/shortlist`} label="확정된 장소" icon={<FileText size={26} />} />
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
        `flex flex-col items-center gap-0.5 pb-2 text-[11px] font-medium ${isActive ? 'text-brand-600' : 'text-ink-500'}`
      }
    >
      {icon}
      {label}
    </NavLink>
  )
}
