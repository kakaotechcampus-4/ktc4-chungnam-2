import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { KakaoMapKeyMissingError, loadKakaoMaps } from './kakaoMap'
import { createMarkerLayer, type MarkerLayer } from './markerLayer'
import { createCandidateMarkerElement, createSearchMarkerElement, markSelected } from './pinMarker'
import type { PlaceSearchResultDto } from '@/features/search/model'
import { isDesktopNow } from '@/features/shell/useIsDesktop'
import type { RouteDrawing } from '@/features/shortlist/model'
import Pingo from '@/ui/Pingo'
import PingoLoading from '@/ui/PingoLoading'

import { isPlaced, type Pin } from './model'

/** 핀이 하나라도 있으면 곧바로 bounds 로 덮어쓴다. 빈 지도에서만 보이는 값이다(v1 장소 데이터는 서울). */
const FALLBACK_CENTER = { lat: 37.5665, lng: 126.978 }

/** 검색창·칩 아래, 지도가 가려지지 않기 시작하는 높이(px). */
const VISIBLE_TOP = 170

/** 핀을 고르면 이 레벨까지 다가간다 — 골목과 이웃 핀이 보이는 축척. 이미 더 가까우면 그대로 둔다(#843). */
const FOCUS_LEVEL = 3

/** 확대 애니메이션 시간(ms). 옮기기는 카카오 panTo 의 기본 시간을 쓴다. */
const ZOOM_MS = 300

export type SearchMarker = {
  n: number
  name: string
  category?: PlaceSearchResultDto['category']
  lat: number
  lng: number
  selected: boolean
  onClick: () => void
}

/**
 * 고른 검색 핀을 끌어안는 핑고의 자리(px, 좌표 = 꼬리 끝에서 위로). 검색 핀(pinMarker)이 1.25배로 머문 크기 기준이다.
 * - 원 가운데 27.5 · 원 위끝 46: 그림 32×38 에서 원 가운데 y16, 위끝 y1 을 1.25배
 * - 핑고(30px) 눈 바로 아래(위에서 19.5)에 원 위끝이 오게 → 핑고 위끝 66
 */
const HUG = { size: 30, top: 66, circleMid: 27.5 }

/** 올리기 전 AI 후보(#843) — 요청한 사람의 화면에만 점선 핀으로 그린다. */
export type CandidateMarker = { id: string; rank: number; name: string; lat: number; lng: number; selected: boolean; onClick: () => void }

/** 지도 버튼(현재 위치·최근 핀·전체 핀)·검색·핀·AI 후보 선택이 지도를 움직이는 통로. */
export type MapController = {
  panTo: (lat: number, lng: number) => void
  /** 고른 곳으로 부드럽게 옮기고, 멀리 보고 있었으면 FOCUS_LEVEL 까지 부드럽게 확대한다. */
  focusPin: (lat: number, lng: number) => void
  getCenter: () => { lat: number; lng: number }
  fitPins: (points: { lat: number; lng: number }[]) => void
}

/**
 * 화면 전체를 덮는 지도. 탭을 바꿔도 다시 만들지 않으려고 MapLayout 에 한 번만 둔다.
 * 넓은 화면에서는 왼쪽 패널 오른쪽부터 시작한다(`leftInset`, #338).
 * 마커는 React 바깥(markerLayer)에서 산다 — frontend/CLAUDE.md.
 */
export default function MapCanvas({
  pins,
  memberCount,
  selectedPinId = null,
  results = [],
  candidates = [],
  route = [],
  onSelect,
  onReady,
  onMovingChange,
  onMapClick,
  leftInset = 0,
}: {
  pins: Pin[]
  /** 핀 색(참여율)의 분모 — 지도 전체 구성원 수. */
  memberCount: number
  /** 상세를 연 핀(주소의 ?pin=). 지도에서 강조한다. */
  selectedPinId?: string | null
  /** 장소 검색 결과(Figma 4절) — 파란 핀으로 띄운다. 핀이 아니다. */
  results?: SearchMarker[]
  /** AI 추천 탭의 올리기 전 후보. 핀이 아니다. */
  candidates?: CandidateMarker[]
  /** 확정 탭 「동선 보기」 또는 AI 코스 지도 보기 — 경로선·순서 번호·구간 시간. */
  route?: RouteDrawing[]
  onSelect: (pinId: string) => void
  onReady: (controller: MapController) => void
  /** 사용자가 지도를 끌기 시작하면 true, 멈추면 false. */
  onMovingChange: (moving: boolean) => void
  /** 지도 빈 곳을 눌렀다(핀·후보·검색 결과를 누르거나 끌고 놓은 건 아니다). 고른 것을 푸는 자리다. */
  onMapClick: () => void
  /** 지도 왼쪽을 가리는 패널 폭(px). 넓은 화면에서 패널이 열려 있을 때만 0이 아니다. */
  leftInset?: number
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const layerRef = useRef<MarkerLayer | null>(null)
  // 콜백이 바뀔 때마다 지도를 다시 만들면 깜빡인다. 최신 참조만 갈아끼운다.
  const callbacks = useRef({ onSelect, onReady, onMovingChange, onMapClick })
  useLayoutEffect(() => {
    callbacks.current = { onSelect, onReady, onMovingChange, onMapClick }
  })
  const fittedRef = useRef(false)
  const mapRef = useRef<{ maps: typeof kakao.maps; map: kakao.maps.Map } | null>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  useEffect(() => {
    let cancelled = false
    let detach = () => {}

    loadKakaoMaps()
      .then((maps) => {
        if (cancelled || !containerRef.current) return
        const map = new maps.Map(containerRef.current, {
          center: new maps.LatLng(FALLBACK_CENTER.lat, FALLBACK_CENTER.lng),
          level: 5,
        })
        const layer = createMarkerLayer(maps, map, (pinId) => callbacks.current.onSelect(pinId))
        layerRef.current = layer

        // focusPin 이 옮기기를 마치고 확대하려고 기다리는 중이면 그 idle 처리기.
        let pendingZoom: (() => void) | null = null
        const cancelZoom = () => {
          if (pendingZoom) maps.event.removeListener(map, 'idle', pendingZoom)
          pendingZoom = null
        }

        const onDragStart = () => {
          // 옮기는 도중에 사용자가 지도를 잡으면 뒤늦게 확대하지 않는다.
          cancelZoom()
          callbacks.current.onMovingChange(true)
        }
        const onIdle = () => callbacks.current.onMovingChange(false)
        const onClick = () => callbacks.current.onMapClick()
        maps.event.addListener(map, 'dragstart', onDragStart)
        maps.event.addListener(map, 'idle', onIdle)
        maps.event.addListener(map, 'click', onClick)
        detach = () => {
          cancelZoom()
          maps.event.removeListener(map, 'dragstart', onDragStart)
          maps.event.removeListener(map, 'idle', onIdle)
          maps.event.removeListener(map, 'click', onClick)
        }

        mapRef.current = { maps, map }
        // 지도 가운데는 2단계 시트 뒤에 숨는다. 고른 곳은 검색창 아래 ~ 시트 윗변 사이 가운데에 오게 가운데보다 이만큼(px) 위에 둔다.
        // 넓은 화면은 지도 영역에 가리는 시트가 없어서 가운데 그대로다.
        const sheetLift = () => {
          if (isDesktopNow()) return 0
          const h = window.innerHeight
          return Math.round(h / 2 - (VISIBLE_TOP + h * 0.41) / 2)
        }
        callbacks.current.onReady({
          panTo: (lat, lng) => {
            map.setCenter(new maps.LatLng(lat, lng))
            map.panBy(0, sheetLift())
          },
          // 옮기고 나서 고른 곳을 붙든 채(anchor) 확대한다. 한꺼번에 하면 확대 중심이 화면 밖일 수 있다.
          focusPin: (lat, lng) => {
            cancelZoom()
            const target = new maps.LatLng(lat, lng)
            const zoomIn = map.getLevel() > FOCUS_LEVEL
            if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
              if (zoomIn) map.setLevel(FOCUS_LEVEL)
              map.setCenter(target)
              map.panBy(0, sheetLift())
              return
            }
            const zoom = () => map.setLevel(FOCUS_LEVEL, { anchor: target, animate: { duration: ZOOM_MS } })
            // 고른 곳이 보이는 자리에 오게 하는 가운데(지금 축척 기준).
            const proj = map.getProjection()
            const p = proj.containerPointFromCoords(target)
            const c = proj.containerPointFromCoords(map.getCenter())
            const lift = sheetLift()
            // 이미 그 자리면 옮길 게 없어서 idle 이 오지 않는다 — 바로 확대한다.
            if (Math.hypot(p.x - c.x, p.y + lift - c.y) < 1) {
              if (zoomIn) zoom()
              return
            }
            if (zoomIn) {
              pendingZoom = () => {
                cancelZoom()
                zoom()
              }
              maps.event.addListener(map, 'idle', pendingZoom)
            }
            map.panTo(proj.coordsFromContainerPoint(new maps.Point(p.x, p.y + lift)))
          },
          getCenter: () => {
            const c = map.getCenter()
            return { lat: c.getLat(), lng: c.getLng() }
          },
          fitPins: (list) => layer.fit(list),
        })
        setReady(true)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        // 지도가 안 뜨는 건 조용히 넘길 일이 아니다. 화면에도 콘솔에도 남긴다.
        console.error('[map] 카카오맵 초기화 실패', err)
        setError(err instanceof Error ? err : new Error(String(err)))
      })

    return () => {
      cancelled = true
      detach()
      layerRef.current?.destroy()
      layerRef.current = null
    }
  }, [])

  useEffect(() => {
    const layer = layerRef.current
    if (!ready || !layer) return

    layer.sync(pins, memberCount)

    // 처음 핀이 들어왔을 때만 시야를 맞춘다. 매번 하면 사용자가 옮긴 시야를 뺏는다.
    if (!fittedRef.current && pins.length > 0) {
      layer.fit(pins.filter(isPlaced))
      fittedRef.current = true
    }
  }, [pins, memberCount, ready])

  useEffect(() => {
    if (ready) layerRef.current?.select(selectedPinId)
  }, [selectedPinId, pins, ready])

  // 패널을 접고 펼치면 지도 틀의 왼쪽 끝이 움직인다. 카카오맵은 CSS 로 바뀐 크기를 모르니 다시 재게 하고,
  // 보던 장소가 화면에서 같은 자리에 남게 한다. relayout 은 가운데가 아니라 틀 왼쪽 위를 붙잡고 있어서,
  // 바꾸기 전 가운데가 지금 어디 있는지 보고 원래 화면 위치(새 가운데에서 움직인 폭의 절반만큼 반대쪽)로 옮긴다.
  const lastInset = useRef(leftInset)
  useEffect(() => {
    const delta = leftInset - lastInset.current
    lastInset.current = leftInset
    // 지도가 뜨기 전이면 처음부터 바뀐 틀에 맞춰 만들어진다.
    const m = mapRef.current
    if (!m || delta === 0) return
    const before = m.map.getCenter()
    m.map.relayout()
    const proj = m.map.getProjection()
    const p = proj.containerPointFromCoords(before)
    m.map.setCenter(proj.coordsFromContainerPoint(new m.maps.Point(p.x + delta / 2, p.y)))
  }, [leftInset])

  // 검색 결과 파란 핀. 몇 개 안 되고 검색할 때마다 통째로 바뀌어서 매번 새로 그린다.
  // 고를 때마다 다시 그리니 새로 고른 핀만 한 번 튄다(pin-bounce).
  useEffect(() => {
    const m = mapRef.current
    if (!ready || !m) return
    const overlays = results.map((r) => {
      const el = createSearchMarkerElement(r, r.onClick)
      const overlay = new m.maps.CustomOverlay({
        position: new m.maps.LatLng(r.lat, r.lng),
        content: el,
        yAnchor: 1,
        clickable: true,
        zIndex: r.selected ? 12 : 5,
      })
      overlay.setMap(m.map)
      return overlay
    })
    return () => overlays.forEach((o) => o.setMap(null))
  }, [results, ready])

  // 고른 검색 핀을 핑고가 위에서 끌어안는다. 몸은 원 뒤(zIndex 11 < 핀 12)에 두고, 원을 감싼 손은 핀이 앞에 그린다.
  // 원 뒤에서 올라오고, 다른 결과를 고르거나 풀면 원 뒤로 내려간다 — 원 가운데 아래는 잘라서 원 밖으로 삐져나오지 않는다.
  // 들어가는 핑고와 올라오는 핑고가 잠깐 같이 있어도 된다. 핑고는 누름을 받지 않는다(아래 지도로 간다).
  const hugAt = results.find((r) => r.selected)
  const hugLat = hugAt?.lat
  const hugLng = hugAt?.lng
  useEffect(() => {
    const m = mapRef.current
    if (!ready || !m || hugLat == null || hugLng == null) return
    // 바깥 상자의 아래끝이 좌표(꼬리 끝)다. 안쪽 상자가 핑고 위끝부터 원 가운데까지만 보인다.
    const box = document.createElement('div')
    box.style.cssText = `width:${HUG.size}px;height:${HUG.top}px;pointer-events:none;line-height:0`
    const clip = document.createElement('div')
    clip.style.cssText = `height:${HUG.top - HUG.circleMid}px;overflow:hidden`
    const inner = document.createElement('div')
    inner.className = 'pingo-rise'
    clip.appendChild(inner)
    box.appendChild(clip)
    const root = createRoot(inner)
    root.render(<Pingo size={HUG.size} mood="hug" />)
    const overlay = new m.maps.CustomOverlay({ position: new m.maps.LatLng(hugLat, hugLng), content: box, yAnchor: 1, zIndex: 11 })
    overlay.setMap(m.map)
    return () => {
      const remove = () => {
        overlay.setMap(null)
        // 렌더 도중에 지우면 React 가 경고한다 — 다음 틱에 뗀다.
        queueMicrotask(() => root.unmount())
      }
      if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) return remove()
      inner.className = 'pingo-sink'
      inner.addEventListener('animationend', remove, { once: true })
    }
  }, [hugLat, hugLng, ready])

  // AI 후보 점선 핀. 많아야 몇 곳이고 결과·선택이 바뀔 때만 와서 검색 결과처럼 매번 새로 그린다. 고른 후보는 핀 위로 올린다.
  useEffect(() => {
    const m = mapRef.current
    if (!ready || !m) return
    const overlays = candidates.map((c) => {
      const el = createCandidateMarkerElement(c, c.onClick)
      if (c.selected) markSelected(el, c.name, true)
      const overlay = new m.maps.CustomOverlay({
        position: new m.maps.LatLng(c.lat, c.lng),
        content: el,
        yAnchor: 1,
        clickable: true,
        zIndex: c.selected ? 11 : 4,
      })
      overlay.setMap(m.map)
      return overlay
    })
    return () => overlays.forEach((o) => o.setMap(null))
  }, [candidates, ready])

  // 동선(Figma 7절): brand-600 4px 직선, 순서 번호는 골드 + 갈색 숫자, 구간 "약 N분" 흰 알약.
  // AI 코스(#683)는 날짜마다 색과 선 모양을 달리하고, 번호 원과 알약 테두리도 그날 색이다.
  useEffect(() => {
    const m = mapRef.current
    if (!ready || !m) return
    const { maps, map } = m
    const drawn: { setMap: (map: kakao.maps.Map | null) => void }[] = []
    const overlay = (lat: number, lng: number, html: HTMLElement, yAnchor = 0.5) => {
      const o = new maps.CustomOverlay({ position: new maps.LatLng(lat, lng), content: html, yAnchor, zIndex: 6 })
      o.setMap(map)
      drawn.push(o)
    }
    for (const r of route) {
      const color = `var(${r.color ?? '--brand-600'})`
      if (r.stops.length >= 2) {
        const line = new maps.Polyline({
          path: r.stops.map((s) => new maps.LatLng(s.lat, s.lng)),
          strokeWeight: r.color ? 5 : 4,
          strokeColor: getComputedStyle(document.documentElement).getPropertyValue(r.color ?? '--brand-600').trim() || '#2A57C4',
          strokeOpacity: 1,
          strokeStyle: r.style ?? 'solid',
        })
        line.setMap(map)
        drawn.push(line)
      }
      for (const s of r.stops) {
        const el = document.createElement('span')
        el.textContent = String(s.n)
        const fill = r.color ? `background:${color};color:#fff` : 'background:var(--pin-confirmed);color:var(--pin-confirmed-mark)'
        el.style.cssText =
          `display:flex;width:18px;height:18px;align-items:center;justify-content:center;border-radius:50%;${fill};border:2px solid #fff;font:700 11px/1 var(--font-sans);transform:translate(14px,-34px)`
        overlay(s.lat, s.lng, el)
      }
      for (const l of r.legs) {
        const el = document.createElement('span')
        el.textContent = l.label
        const text = r.color ? color : 'var(--brand-700)'
        el.style.cssText =
          `padding:2px 8px;border-radius:999px;background:#fff;border:1px solid ${color};color:${text};font:700 11px/1.4 var(--font-sans);white-space:nowrap`
        overlay((l.from.lat + l.to.lat) / 2, (l.from.lng + l.to.lng) / 2, el)
      }
    }
    return () => drawn.forEach((d) => d.setMap(null))
  }, [route, ready])

  return (
    <div className="fixed inset-0 bg-ink-100" style={leftInset ? { left: leftInset } : undefined}>
      <div ref={containerRef} className="h-full w-full" />
      {!ready && (
        <div className="absolute inset-x-0 top-32 flex flex-col items-center gap-1 px-4 text-center">
          {error ? (
            <>
              <Pingo size={48} mood="error" />
              <p className="text-sm text-warn-text">지도를 불러오지 못했어요</p>
              <p className="text-xs text-ink-500">
                {error instanceof KakaoMapKeyMissingError
                  ? 'frontend/.env.local 에 VITE_KAKAO_MAP_KEY 를 넣어주세요 (.env.example 참고)'
                  : error.message}
              </p>
              <p className="text-xs text-ink-500">핀 {pins.length}개는 아래 목록에 그대로 있어요</p>
            </>
          ) : (
            <PingoLoading label="지도를 불러오는 중…" />
          )}
        </div>
      )}
    </div>
  )
}
