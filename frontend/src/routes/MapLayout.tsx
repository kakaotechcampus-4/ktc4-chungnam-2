import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Link, NavLink, Outlet, useLocation, useMatch, useNavigate, useParams } from 'react-router'
import { ChevronLeft, ChevronsLeft, ChevronsRight, FileText, MapPin, Route, Search, Users, type LucideIcon } from 'lucide-react'

import AgentButton from '@/features/agent/AgentButton'
import { useMeQuery } from '@/features/auth/queries'
import { ImportSheetHost } from '@/features/kakaoImport/ImportSheet'
import { MIN_LEVEL } from '@/features/map/camera'
import { SchedulePanelHost } from '@/features/shortlist/SchedulePanel'
import { useScheduleOpen } from '@/features/shortlist/scheduleStore'
import MapCanvas, { type MapController } from '@/features/map/MapCanvas'
import { mapTapAction } from '@/features/map/mapTap'
import { usePinSelection } from '@/features/map/usePinSelection'
import { authorName, byNewest, filterPins, isPlaced, timeAgo } from '@/features/map/model'
import { CategoryChips } from '@/features/map/PinFilterControls'
import { livePlaceAnchor, useLivePinResolver } from '@/features/map/livePlaces'
import { usePinsQuery, useResolveLivePin } from '@/features/map/queries'
import { useNewSince, useSaveSeenOnLeave } from '@/features/map/newSince'
import { useMapEvents } from '@/features/map/realtime'
import TrashDropZone from '@/features/map/TrashDropZone'
import { usePinFilters } from '@/features/map/usePinFilters'
import { boundaryCorners, useRegionBoundary } from '@/features/map/regionGeo'
import MapSwitcher from '@/features/maps/MapSwitcher'
import NotificationBell from '@/features/notifications/NotificationBell'
import { AccountMenu } from '@/features/maps/AccountSheet'
import { useMapQuery, useMapsQuery } from '@/features/maps/queries'
import { useAiStore } from '@/features/recommend/aiStore'
import { useRecommendRadiusM, useResultQuery } from '@/features/recommend/queries'
import { firstMapLink } from '@/features/kakaoImport/share'
import { isLinkInput } from '@/features/search/model'
import { useSourcePlacesQuery } from '@/features/search/queries'
import { scheduleDrawing } from '@/features/shortlist/model'
import { useRouteStore } from '@/features/shortlist/routeStore'
import { routeDay } from '@/features/shortlist/schedule'
import { useTripSchedule } from '@/features/shortlist/useTripSchedule'
import { useCourseMapStore } from '@/features/course/courseMapStore'
import { useRecentSearches } from '@/features/search/recentSearchStore'
import RecentSearches from '@/features/search/RecentSearches'
import { useSearchStore } from '@/features/search/searchStore'
import AppMenu from '@/features/shell/AppMenu'
import { PANEL_GAP, PANEL_W, panelCover, TAB_BAR_H } from '@/features/shell/layout'
import MapControls, { type ControlKey } from '@/features/shell/MapControls'
import { backAriaLabel, usePanelBackStore } from '@/features/shell/panelBack'
import ProfileModal, { ProfileMenu } from '@/features/shell/ProfileModal'
import { useSheetStore } from '@/features/shell/sheetStore'
import type { ShellContext } from '@/features/shell/shellContext'
import { ConnectionBanner } from '@/features/shell/TabSheet'
import { showToast } from '@/features/shell/toast'
import Toaster from '@/features/shell/Toaster'
import { useIsDesktop, useIsPc } from '@/features/shell/useIsDesktop'
import ErrorBoundary from '@/ui/ErrorBoundary'
import { PingoMark } from '@/ui/Pingo'
import { ClearButton } from '@/ui/TextField'
import Wordmark from '@/ui/Wordmark'

/** 넓은 화면 패널이 미끄러지는 시간. 패널·덧칠의 `duration-300` 과 같은 값이다. */

/**
 * 지도 하나 안의 화면(최종기획안 4절). 지도는 항상 떠 있고, 하단 탭 4개(마킹·AI 추천·확정·AI 코스)가 그 위 바텀시트 내용을 바꾼다.
 * 지도는 여기 한 번만 만든다 — 탭마다 만들면 탭을 바꿀 때마다 지도가 다시 뜬다.
 *
 * 넓은 화면(768px 이상, #338)은 왼쪽 408px 패널(파란 머리: ☰·워드마크·탭 4개, 그 아래 지도 제목·검색·탭 내용, #1538) + 오른쪽 지도 영역이다.
 * 태블릿(768~1023px)은 내용 패널만 360으로 좁다(#603).
 * 칩·연결 띠·지도 버튼·토스트는 지도 영역에 둔다. 패널과 모바일은 같은 트리를 쓰고 틀의 클래스만 바꾼다 —
 * 768px 경계를 넘나들어도 탭 내용(쓰던 의견 등)이 다시 마운트되지 않게.
 */
export default function MapLayout() {
  const { mapId = '' } = useParams()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const { selectedPinId, selectPin } = usePinSelection()
  const { data: loadedPins } = usePinsQuery(mapId)
  const allPins = useMemo(() => loadedPins ?? [], [loadedPins])
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
  const onCourseTab = useMatch('/maps/:mapId/course') !== null
  // AI 코스 탭은 확정 리스트로 짜는 곳이라 지도도 확정 탭과 같게 본다(확정 핀만). 핀을 누르면 그 탭 안에서 상세를 연다.
  const onConfirmedTab = onShortlistTab || onCourseTab
  // 마커와 목록이 같은 필터를 본다. 확정·코스 탭은 확정 핀만, 다른 탭엔 필터가 없어 전부 보인다.
  const pins = onConfirmedTab ? allPins.filter((p) => p.kind === '확정') : filterPins(allPins, filters, memberCount)
  const routeOn = useRouteStore((s) => s.on) && onShortlistTab
  const routeChosen = useRouteStore((s) => s.day)
  // 일정은 서버가 기간·확정 리스트에 맞춰 둔다(#1172). 여기서는 동선 보기로 고른 날의 순서만 꺼낸다.
  const trip = useTripSchedule(mapId)
  const course = useCourseMapStore()
  // 확정 탭은 「동선 보기」로 고른 날의 일정 순서대로, AI 코스 탭은 이 지도의 코스(#683) 선을 긋는다 — 한 화면에 둘이 겹치지 않는다.
  const routeDrawings = useMemo(() => {
    if (onShortlistTab) {
      const day = routeOn ? routeDay(trip.schedule, trip.dates, routeChosen) : null
      return day ? [scheduleDrawing(trip.schedule.days[day] ?? [], allPins)] : []
    }
    return onCourseTab && course.mapId === mapId ? course.days : []
  }, [onShortlistTab, routeOn, routeChosen, trip.schedule, trip.dates, allPins, onCourseTab, course.mapId, course.days, mapId])
  const markingStage = useSheetStore((s) => s.stages.map)
  const setStage = useSheetStore((s) => s.setStage)
  const search = useSearchStore()
  const [searchText, setSearchText] = useState('')
  const [searchFocused, setSearchFocused] = useState(false)
  const me = useMeQuery().data
  const myId = me?.id
  const myMaps = useMapsQuery().data?.items ?? []
  const recent = useRecentSearches(myId)
  const recentOpen = searchFocused && !searchText && recent.list.length > 0
  // 마지막으로 본 뒤 새 핀·의견이 있는 핀에 파란 점(#1454). 목록(MapTab)과 같은 기준이고, 지도를 떠날 때 지금 모습을 적는다.
  // 받기 전(loadedPins 없음)에 떠나면 적지 않는다 — 빈 모습을 적으면 다음에 모든 핀이 새 핀으로 보인다.
  const { news } = useNewSince(mapId, loadedPins, myId)
  useSaveSeenOnLeave(mapId, loadedPins, myId)
  const freshKey = [...news.keys()].sort().join(',')
  const freshPinIds = useMemo(() => new Set(freshKey ? freshKey.split(',') : []), [freshKey])
  // 결과 시트에서 「닫기」를 눌러도 입력칸에 글자가 남지 않게, 검색이 닫히면 같이 비운다(#351).
  const [lastSource, setLastSource] = useState(search.source)
  if (lastSource !== search.source) {
    setLastSource(search.source)
    if (search.source === null) setSearchText('')
    // 오타 제안(「중국집」으로 다시 찾기)처럼 입력칸 밖에서 검색해도 입력칸이 그 검색어를 보인다.
    else if (search.source.kind === 'name') setSearchText(search.source.query)
  }
  const found = useSourcePlacesQuery(search.source, search.near).data?.places
  // 검색 결과 파란 핀 — 결과나 선택이 바뀔 때만 다시 그린다.
  const searchMarkers = useMemo(
    () =>
      (found ?? []).map((r, i) => ({
        id: r.place_id,
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

  // AI 추천 탭에선 올리기 전 후보를 핑고 핀으로 그린다(#843). 요청한 사람의 화면에만 있고 지도(핀 목록)는 바꾸지 않는다(가드레일 1).
  // 올린 후보는 이미 핀으로 떠 있어서 빼고, 좌표가 없는 후보도 뺀다. 결과는 추천 탭과 같은 캐시를 본다.
  const onRecommendTab = useMatch('/maps/:mapId/recommend') !== null
  // AI 추천은 보이는 지도 가운데 반경 안에서 찾는다(#1385) — 그 탭에서만 여행 지역 경계·그 밖 어둡게·반경 원을 그린다.
  // 경계 파일도 그 탭에서만 받는다(시·도 하나에 수십 KB). 한 번 받으면 캐시에 남는다.
  const regionBoundary = useRegionBoundary(onRecommendTab ? mapInfo?.region?.label : undefined)
  const run = useAiStore((s) => s.runs[mapId])
  const result = useResultQuery(run?.status === 'done' ? run : undefined).data
  // 원 반경은 준비 화면에서 고른 카테고리의 서버 값이다(Readiness.radius_m, #1468). 없으면 원을 그리지 않는다.
  const recommendRadiusM = useRecommendRadiusM(mapId)
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
    runSearch(searchText.trim())
  }

  function runSearch(q: string) {
    if (!q) return
    // 검색은 마킹 탭의 일이다. 다른 탭에서 검색해도 마킹 탭으로 가서 결과를 보여준다.
    if (!onMarkingTab) navigate(`/maps/${mapId}`)
    const center = controller.current?.getCenter() ?? null
    // 지도 링크를 붙여넣었으면 이름 대신 링크로 장소를 찾는다(#487). 같은 결과 시트에서 핀을 찍는다.
    // 카톡 말풍선 「[카카오맵] 가게 / 주소 / 링크」를 통째로 붙여 넣어도 그 안의 링크로 찾는다.
    const link = isLinkInput(q) ? q : firstMapLink(q)
    if (link) search.openLink(link, center)
    else {
      search.submit(q.slice(0, 50), center)
      recent.add(q.slice(0, 50))
    }
    setStage('map', 2)
  }

  function clearSearch() {
    setSearchText('')
    search.close()
  }
  const mapMoving = useSheetStore((s) => s.mapMoving)
  const setMapMoving = useSheetStore((s) => s.setMapMoving)
  const modalOpen = useSheetStore((s) => s.modalOpen)
  const controller = useRef<MapController | null>(null)
  const [activeControl, setActiveControl] = useState<ControlKey | null>(null)
  const [profileOpen, setProfileOpen] = useState(false)
  const panelBack = usePanelBackStore((s) => s.back)

  // 검색은 지도 하나 안의 잠깐 작업이다. 지도를 떠나면(다른 지도로 바꿔도) 닫는다 — 다음 지도에 이전 검색 결과가 남지 않게.
  useEffect(() => () => useSearchStore.getState().close(), [])

  const openProfile = setProfileOpen

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
  // 근처 찾기는 누른 자리 둘레(100m)라 결과가 이미 화면 안이기 쉽다. 그래도 결과에 맞춰 가장 가까운 축척까지 확대한다(#1174).
  const tapSearch = search.source?.kind === 'tap'
  useEffect(() => {
    if (found?.length) controller.current?.fitPins(found, tapSearch ? { force: true, closest: MIN_LEVEL } : undefined)
  }, [found, tapSearch])
  useEffect(() => {
    const r = found?.find((f) => f.place_id === search.selectedId)
    if (r) controller.current?.focusPin(r.lat, r.lng)
  }, [found, search.selectedId])

  // AI 후보를 고르면(카드·지도 핑고 핀) 그 후보로 간다(#843). 올린 후보는 그 자리의 핀으로 간다.
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
    const key = `${run.id}-${run.attempt_no}-${run.default_radius_m ?? 0}`
    if (fittedResult.current === key) return
    const points = result.candidates.flatMap((c) => (c.lat == null || c.lng == null ? [] : [{ lat: c.lat, lng: c.lng }]))
    if (!points.length) return
    fittedResult.current = key
    controller.current?.fitPins(points)
  }, [onRecommendTab, mapReady, run, result])

  // 지도 빈 곳 누르기는 어느 탭이든 같다(#1028, 멘토 리뷰 #816). 고른 것(핀 상세·검색 결과·AI 후보)이 있으면 풀고,
  // 없으면 누른 자리에 「이 근처 장소 찾기」 말풍선을 띄운다 — 둘러보다 누른 것이 바로 검색이 되지 않게. 지도는 그대로 둔다.
  const [tapAt, setTapAt] = useState<{ lat: number; lng: number } | null>(null)
  // 탭을 바꾸거나 무엇을 고르거나 검색이 열리면 말풍선은 닫는다(렌더 중에 맞춘다 — 위 lastQuery 와 같은 방식).
  const tapContext = `${pathname}|${selectedPinId}|${search.source ? 'search' : ''}|${candidateFocus?.id ?? ''}`
  const [lastTapContext, setLastTapContext] = useState(tapContext)
  if (lastTapContext !== tapContext) {
    setLastTapContext(tapContext)
    setTapAt(null)
  }
  function onMapClick(at: { lat: number; lng: number } | null) {
    const search = useSearchStore.getState()
    const ai = useAiStore.getState()
    const action = mapTapAction({ selected: Boolean(selectedPinId || search.selectedId || ai.focus), bubbleOpen: tapAt !== null, at })
    if (action === 'release') {
      if (selectedPinId) selectPin(null)
      if (search.selectedId) search.select(null)
      if (ai.focus) ai.blurCandidate()
    }
    setTapAt(action === 'open' ? at : null)
  }
  /** 말풍선을 누르면 마킹 탭에서 누른 자리 근처의 핀으로 만들 수 있는 장소를 찾는다(#486). */
  function searchNearby(at: { lat: number; lng: number }) {
    setTapAt(null)
    if (!onMarkingTab) navigate(`/maps/${mapId}`)
    useSearchStore.getState().openTap(at)
    setStage('map', 2)
    // 접힌 패널에선 결과를 볼 곳이 없다(넓은 화면).
    useSheetStore.getState().setPanelOpen(true)
  }
  // AI 탭을 떠나면 후보 강조를 푼다 — 남아 있으면 다른 탭의 첫 누름이 보이지 않는 후보 풀기에 쓰인다.
  useEffect(() => {
    if (!onRecommendTab) useAiStore.getState().blurCandidate()
  }, [onRecommendTab])

  const onMovingChange = useCallback(
    (moving: boolean) => {
      setMapMoving(moving)
      // 사용자가 지도를 직접 옮기면 "최근 핀·전체 핀을 보는 중" 표시도, 누른 자리의 말풍선도 더 맞지 않다.
      if (moving) {
        setActiveControl(null)
        setTapAt(null)
      }
    },
    [setMapMoving],
  )

  function onControl(key: ControlKey) {
    const map = controller.current
    if (!map) return showToast('지도를 아직 불러오는 중이에요')
    // 최근 핀은 필터와 상관없이 지도 전체에서, 전체 핀 보기는 지금 보이는(필터된) 핀으로.
    // 확정·코스 탭은 지도에 확정 핀만 그리니 최근 핀도 그 안에서 찾는다 — 안 보이는 핀으로 옮기지 않게.
    const placed = (key === 'recent' && !onConfirmedTab ? allPins : pins).filter(isPlaced)

    if (key === 'locate') {
      if (!navigator.geolocation) return showToast('이 브라우저에서는 현재 위치를 쓸 수 없어요')
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
        // 기본은 끝없이 기다려서, 응답 없는 기기에선 눌러도 아무 일이 없었다.
        { timeout: 10_000 },
      )
      return
    }
    if (placed.length === 0)
      return showToast(
        onConfirmedTab ? '아직 확정된 장소가 없어요' : pins.length < allPins.length ? '필터에 맞는 핀이 없어요' : '아직 지도에 핀이 없어요',
      )
    if (key === 'recent') {
      const pin = [...placed].sort(byNewest)[0]
      map.panTo(pin.lat!, pin.lng!)
      const who = [authorName(pin), timeAgo(pin.created_at)].filter(Boolean).join(' · ')
      showToast(`가장 최근 핀: ${pin.place_name ?? '이름 없는 핀'} (${who})`)
    } else {
      // 누른 사람이 원한 것이라 이미 다 보여도 맞춘다(#1026).
      map.fitPins(placed, { force: true })
      showToast(`핀 ${placed.length}곳을 모두 보여 드려요`)
    }
    setActiveControl(key)
  }

  // 지도가 아직 없거나 못 띄웠으면(SDK 실패, e2e) 지도가 처음 뜰 자리 대신 핀들의 위치 기준을 쓴다 — 추천 run 은 center 가 필수다(#1331).
  const context: ShellContext = {
    mapId,
    activeControl,
    onControl,
    connection,
    getCenter: () => controller.current?.getCenter() ?? livePlaceAnchor(allPins, mapInfo?.regionCenter),
    showRegion: () => {
      if (regionBoundary) controller.current?.fitPins(boundaryCorners(regionBoundary), { force: true })
      else if (mapInfo?.regionCenter) controller.current?.panTo(mapInfo.regionCenter.lat, mapInfo.regionCenter.lng)
    },
  }
  // 3단계에서는 칩이 시트 제목 아래로 옮겨 간다(MapTab). 넓은 화면엔 단계가 없다. 검색 중에는 숨긴다(Figma 규칙).
  const chipsShown = onMarkingTab && (desktop || markingStage !== 3) && !search.source
  const fade = mapMoving ? 'opacity-0 duration-150' : 'opacity-100 delay-800 duration-300'
  // 「일정 짜기」 옆 패널이 열려 있으면 지도 위 토스트·버튼·칩이 그 오른쪽으로 비킨다(패널이 가리지 않게).
  const sideOpen = useScheduleOpen(mapId) && onShortlistTab && desktop
  // 지도는 늘 화면 전체이고 패널은 그 위에 뜬 카드다(#1538). 지도 위 덧칠(칩·« 손잡이)과 카메라는 카드가 가린 폭만큼 비킨다.
  const cover = desktop ? panelCover(panelOpen, panelW, sideOpen) : 0

  return (
    <>
      <MapCanvas
        pins={pins}
        freshPinIds={freshPinIds}
        // 핀이 없으면 지도 만들 때 고른 지역에서 시작한다(없으면 서울).
        startCenter={mapInfo?.regionCenter}
        selectedPinId={selectedPinId}
        memberCount={memberCount}
        results={searchMarkers}
        candidates={candidates}
        route={routeDrawings}
        // 원은 준비 화면(run 없음)에만 그린다. 결과의 다시 추천·넓히기는 run을 만들 때의 가운데에서 찾아서, 지도를 따라가는 원은 그 범위와 어긋난다.
        recommendArea={onRecommendTab ? { boundary: regionBoundary, radiusM: run ? null : recommendRadiusM } : null}
        // 확정 탭에서 누른 핀은 확정 탭 안에서 연다(「‹ 확정된 장소」로 돌아온다).
        onSelect={(pinId) => {
          setPanelOpen(true)
          // 검색 결과를 보다가 핀을 고르면 매달린 핑고는 들어간다.
          useSearchStore.getState().select(null)
          // 코스 탭은 코스 탭 안에서 연다 — 확정 탭으로 넘어가면 코스 선이 사라진다(#1127 리뷰).
          // 탭 안에서 열 때는 주소의 다른 값(카테고리·필터)을 남긴다. 주소를 통째로 바꾸면 켜 둔 필터가 풀린다.
          if (onMarkingTab || onConfirmedTab) selectPin(pinId)
          else navigate(`/maps/${mapId}?pin=${encodeURIComponent(pinId)}`)
        }}
        onResultGroup={(ids) => {
          useSearchStore.getState().showGroup(ids)
          // 접힌 패널에선 묶인 곳 목록을 볼 곳이 없다(넓은 화면).
          setPanelOpen(true)
        }}
        onReady={onMapReady}
        onMovingChange={onMovingChange}
        onMapClick={onMapClick}
        tapBubble={tapAt && { ...tapAt, onPress: () => searchNearby(tapAt) }}
        leftCover={cover}
      />

      {/* 모바일은 'contents' 라 틀이 없고 안쪽이 각자 화면에 붙는다. 넓은 화면은 이 틀이 지도 위에 뜬 왼쪽 패널 카드다(#1538). */}
      {/* 접기는 화면 왼쪽 밖으로 left 를 옮겨 미끄러뜨린다 — transform 이면 안쪽 fixed 확인 창이 패널 기준으로 잡힌다. */}
      {/* 다 접히면 invisible + inert 로 보이지도, 포커스가 들어가지도 않는다. */}
      <div
        id="map-panel"
        inert={desktop && !panelOpen}
        style={desktop ? { left: panelOpen ? PANEL_GAP : -panelW, width: panelW } : undefined}
        className={
          desktop
            ? `fixed inset-y-3 z-30 flex flex-col overflow-hidden rounded-2xl bg-white shadow-float transition-[left,visibility] duration-300 ease-out motion-reduce:transition-none ${
                panelOpen ? 'visible' : 'invisible'
              }`
            : 'contents'
        }
      >
        {/* 넓은 화면 pb-1: 검색창 포커스 테두리(바깥 4px)가 바로 아래 탭 내용(흰 바탕)에 덮이지 않게 자리를 둔다. */}
        <header
          data-map-header
          // 최근 검색 목록이 열리면 바텀시트(z-30) 위쪽에 붙은 지도 버튼보다 위로 올린다.
          className={desktop ? 'shrink-0 space-y-3 px-4 pb-1 pt-3' : `pointer-events-none fixed inset-x-0 top-0 ${searchFocused ? 'z-40' : 'z-20'} space-y-2 px-4 pt-3`}
        >
          {/* 넓은 화면의 파란 머리(카카오맵 왼쪽 패널 모양, #1538) — ☰ 메뉴 · 워드마크 · 탭 4개. 탭은 패널을 접으면 같이 접힌다. */}
          {desktop && (
            <div className="-mx-4 -mt-3 bg-brand-600 px-4 pt-3">
              <div className="flex h-8 items-center gap-2">
                <AppMenu mapId={mapId} />
                <Wordmark onFill className="h-5 w-auto" />
              </div>
              <nav aria-label="지도 탭" className="mt-2 flex gap-1 pb-2">
                {TABS.map((tab) => (
                  <PanelTab key={tab.path} to={`/maps/${mapId}${tab.path}`} end={tab.end} label={tab.label} />
                ))}
              </nav>
            </div>
          )}
          <div className={desktop ? 'flex items-center gap-2' : 'flex items-center justify-between'}>
            {desktop ? (
              // 넓은 화면의 ‹ 는 패널 안 이전 화면(핀 상세 → 목록 등)이다. 돌아갈 곳이 없으면 없다 — 지도 밖으로는 제목 메뉴로 나간다.
              panelBack && (
                <button
                  type="button"
                  onClick={panelBack.onBack}
                  aria-label={backAriaLabel(panelBack.label)}
                  title={`‹ ${panelBack.label}`}
                  className="press hit-44 flex size-8 shrink-0 items-center justify-center rounded-full text-ink-900"
                >
                  <ChevronLeft size={20} />
                </button>
              )
            ) : (
              <Link
                to="/"
                aria-label="내 지도 목록으로"
                className="press pointer-events-auto hit-44 flex size-8 items-center justify-center rounded-full bg-white text-ink-900 shadow-float"
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
            {desktop && <NotificationBell currentMapId={mapId} />}
            {desktop ? (
              <ProfileMenu
                mapId={mapId}
                trigger={
                  <button
                    type="button"
                    aria-label={`지도 정보와 구성원 ${memberCount}명`}
                    className="hit-44 flex h-8 shrink-0 items-center gap-1 rounded-full border border-ink-200 bg-white px-2.5 text-sm font-bold text-brand-600 press data-[state=open]:border-brand-600 data-[state=open]:bg-brand-50"
                  >
                    <Users size={16} aria-hidden="true" />
                    {memberCount > 0 && memberCount}
                  </button>
                }
              />
            ) : (
              <div className="flex items-center gap-3">
                <NotificationBell floating currentMapId={mapId} />
                <button
                  type="button"
                  aria-label={`지도 정보와 구성원 ${memberCount}명`}
                  onClick={() => openProfile(true)}
                  className="press pointer-events-auto hit-44 flex h-8 items-center gap-1 rounded-full bg-white px-2.5 text-sm font-bold text-brand-600 shadow-float"
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
          {/* 포커스가 검색창이나 최근 검색 목록 안에 있는 동안만 목록을 연다. Esc는 닫는다. */}
          <div
            className="relative"
            onFocus={() => setSearchFocused(true)}
            onBlur={(e) => !e.currentTarget.contains(e.relatedTarget) && setSearchFocused(false)}
            onKeyDown={(e) => e.key === 'Escape' && setSearchFocused(false)}
          >
            <form
              role="search"
              inert={!desktop && mapMoving}
              onSubmit={submitSearch}
              // 최근 검색이 열리면 목록과 한 덩어리로 붙인다 — 아래 모서리를 펴고, 둘레는 brand-600(포커스 표시), 이음매는 옅은 선.
              className={`${desktop ? '' : 'pointer-events-auto '}flex items-center gap-2 border bg-white px-4 py-3 ${desktop ? '' : 'shadow-float transition-opacity '}${
                recentOpen
                  ? 'rounded-t-xl border-brand-600 border-b-ink-100'
                  : `rounded-xl has-[input:focus-visible]:outline-2 has-[input:focus-visible]:outline-offset-2 has-[input:focus-visible]:outline-[var(--line-focus)] ${
                      search.source ? 'border-brand-600' : 'border-ink-200'
                    }`
              }${desktop ? '' : ` ${fade}`}`}
            >
              <input
                id="place-search"
                type="search"
                enterKeyHint="search"
                // 브라우저(크롬·안드로이드 크롬) 입력 기록 목록이 「최근 검색」과 겹쳐 뜨지 않게 끈다.
                autoComplete="off"
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
            {recentOpen && (
              <RecentSearches
                list={recent.list}
                floating={!desktop}
                onPick={(q) => {
                  setSearchText(q)
                  runSearch(q)
                }}
                onRemove={recent.remove}
                onClear={() => {
                  recent.clear()
                  document.getElementById('place-search')?.focus()
                }}
              />
            )}
          </div>
          {!desktop && chipsShown && (
            <CategoryChips
              value={filters.category}
              onChange={(c) => setFilter('category', c)}
              floating
              className={`pointer-events-auto -mx-4 px-4 pb-1 transition-opacity ${fade}`}
            />
          )}
        </header>

        {/* 탭 하나가 죽어도 지도와 탭 바는 남긴다. */}
        <ErrorBoundary resetKey={pathname}>
          <Outlet context={context} />
        </ErrorBoundary>

        {!desktop && (
          <nav
            style={{ minHeight: `calc(${TAB_BAR_H}px + env(safe-area-inset-bottom, 0px))` }}
            className="pb-safe fixed inset-x-0 bottom-0 z-40 grid grid-cols-4 items-end border-t border-ink-100 bg-white"
          >
            {TABS.map((tab) => (
              <TabLink
                key={tab.path}
                to={`/maps/${mapId}${tab.path}`}
                end={tab.end}
                label={tab.label}
                icon={tab.Icon ? <tab.Icon size={24} /> : <PingoMark size={28} />}
              />
            ))}
          </nav>
        )}
      </div>

      {/* 넓은 화면의 지도 영역 위. 지도를 끌 수 있게 누름은 통과시키고, 올린 것들만 다시 받는다. */}
      {desktop && (
        <div
          className="pointer-events-none fixed inset-y-0 right-0 z-20 transition-[left] duration-300 ease-out motion-reduce:transition-none"
          style={{ left: cover }}
        >
          {/* 내 계정(카카오맵 오른쪽 위 원, #1538) — 이름 바꾸기·초대 링크·로그아웃. 지도 정보·구성원은 패널의 구성원 버튼이다. */}
          <div className="pointer-events-auto absolute right-4 top-3 rounded-full bg-white shadow-float">
            <AccountMenu maps={myMaps} name={me?.display_name} />
          </div>
          <div className="absolute left-4 right-20 top-3 flex flex-col items-start gap-2">
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
          {/* 조언은 지도 단위라 네 탭 모두(#1162). */}
          <AgentButton docked mapId={mapId} hidden={modalOpen} fading={mapMoving} />
          {!modalOpen && <Toaster docked controlsVisible={!mapMoving} />}
          {/* 핀을 끌 때만 지도 영역 아래 가운데에 나타난다(#1012). 지도 버튼은 오른쪽이라 겹치지 않는다. */}
          <TrashDropZone mapId={mapId} placement="docked" />
        </div>
      )}

      {profileOpen && !desktop && <ProfileModal mapId={mapId} onClose={() => openProfile(false)} />}
      {/* 카톡 가져오기 시트는 탭 화면 밖 한 자리에서 그린다 — 목록 머리가 바뀌어도 함께 사라지지 않게(#1045). */}
      <ImportSheetHost mapId={mapId} />
      {/* 확정 탭 「일정 짜기」 패널(넓은 화면만) — 탭을 떠나면 닫힌다. */}
      {onShortlistTab && desktop && <SchedulePanelHost mapId={mapId} />}
    </>
  )
}

/**
 * 최종기획안 4절의 탭 3개에 「AI 코스」(#683, 확정 탭의 시트였던 것)를 더한 4개. 라벨은 고정 용어(9절). 하단 탭과 넓은 화면 패널 머리의 탭이 이 표 하나를 쓴다.
 * AI 는 선 아이콘 대신 핑고 얼굴(PingoMark)이다(Icon 없음).
 */
const TABS: { path: string; end?: boolean; label: string; Icon: LucideIcon | null }[] = [
  { path: '', end: true, label: '마킹된 장소', Icon: MapPin },
  { path: '/recommend', label: 'AI 추천', Icon: null },
  { path: '/shortlist', label: '확정된 장소', Icon: FileText },
  { path: '/course', label: 'AI 코스', Icon: Route },
]

/**
 * 하단 탭 칸 하나 — 아이콘 + 11/500 라벨, 비활성 ink-500(흰 바탕 대비 약 5:1). AI 추천도 같은 모양이다(핑고 얼굴).
 * 3칸일 때 가운데에 두던 AI 원(48px, 떠 있음)은 4칸이 되며 둘째 칸에서 왼쪽으로 치우쳐 보여 뺐다(2026-11-03).
 */
function TabLink({ to, end, label, icon }: { to: string; end?: boolean; label: string; icon: ReactNode }) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        `press flex flex-col items-center gap-0.5 rounded-xl pb-2 text-label font-medium ${isActive ? 'text-brand-600' : 'text-ink-500'}`
      }
    >
      {/* 핑고는 선 아이콘보다 커서 같은 칸에 넣어 네 칸 높이를 맞춘다. */}
      <span className="flex size-7 items-center justify-center">{icon}</span>
      {label}
    </NavLink>
  )
}

/**
 * 패널 머리의 탭 하나(#1538). 파란 면 위 흰 14/700 글자, 지금 탭은 brand-700 칸으로 한 단계 진하다(카카오맵 탭 모양).
 * 지금 탭을 다시 누르면 이동하지 않는다 — 이동하면 보던 핀 상세(?pin=)가 사라진다.
 */
function PanelTab({ to, end = false, label }: { to: string; end?: boolean; label: string }) {
  const active = useMatch({ path: to, end }) !== null
  return (
    <NavLink
      to={to}
      end={end}
      onClick={(e) => active && e.preventDefault()}
      className={({ isActive }) =>
        `hit-y-44 flex min-h-9 items-center rounded-md px-3 text-sm font-bold break-keep text-white transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-white ${
          isActive ? 'bg-brand-700' : 'hover:bg-white/15'
        }`
      }
    >
      {label}
    </NavLink>
  )
}

/**
 * 패널 접기·펼치기 손잡이(#338). 지도 영역 왼쪽 끝(펼치면 패널 오른쪽, 접으면 화면 왼쪽 끝) 세로 가운데에 붙는다.
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
      <span className="press flex h-12 w-6 items-center justify-center rounded-r-lg border border-l-0 border-ink-200 bg-white text-ink-600 shadow-float">
        {open ? <ChevronsLeft size={16} aria-hidden="true" /> : <ChevronsRight size={16} aria-hidden="true" />}
      </span>
    </button>
  )
}
