import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { KakaoMapKeyMissingError, loadKakaoMaps } from './kakaoMap'
import { createMarkerLayer, type MarkerLayer } from './markerLayer'
import { isDesktopNow } from '@/features/shell/useIsDesktop'
import type { RouteDrawing } from '@/features/shortlist/model'

import { isPlaced, type Pin } from './model'

/** 핀이 하나라도 있으면 곧바로 bounds 로 덮어쓴다. 빈 지도에서만 보이는 값이다(v1 장소 데이터는 서울). */
const FALLBACK_CENTER = { lat: 37.5665, lng: 126.978 }

/** 검색창·칩 아래, 지도가 가려지지 않기 시작하는 높이(px). */
const VISIBLE_TOP = 170

export type SearchMarker = { n: number; lat: number; lng: number; selected: boolean; onClick: () => void }

/** 지도 버튼(현재 위치·최근 핀·전체 핀)·검색이 지도를 움직이는 통로. */
export type MapController = {
  panTo: (lat: number, lng: number) => void
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
  route = [],
  onSelect,
  onReady,
  onMovingChange,
  leftInset = 0,
}: {
  pins: Pin[]
  /** 핀 색(참여율)의 분모 — 지도 전체 구성원 수. */
  memberCount: number
  /** 상세를 연 핀(주소의 ?pin=). 지도에서 강조한다. */
  selectedPinId?: string | null
  /** 장소 검색 결과(Figma 4절) — 파란 번호 원으로 띄운다. 핀이 아니다. */
  results?: SearchMarker[]
  /** 확정 탭 「동선 보기」 — 경로선·순서 번호·구간 시간. */
  route?: RouteDrawing[]
  onSelect: (pinId: string) => void
  onReady: (controller: MapController) => void
  /** 사용자가 지도를 끌기 시작하면 true, 멈추면 false. */
  onMovingChange: (moving: boolean) => void
  /** 지도 왼쪽을 가리는 패널 폭(px). 넓은 화면에서 패널이 열려 있을 때만 0이 아니다. */
  leftInset?: number
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const layerRef = useRef<MarkerLayer | null>(null)
  // 콜백이 바뀔 때마다 지도를 다시 만들면 깜빡인다. 최신 참조만 갈아끼운다.
  const callbacks = useRef({ onSelect, onReady, onMovingChange })
  useLayoutEffect(() => {
    callbacks.current = { onSelect, onReady, onMovingChange }
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

        const onDragStart = () => callbacks.current.onMovingChange(true)
        const onIdle = () => callbacks.current.onMovingChange(false)
        maps.event.addListener(map, 'dragstart', onDragStart)
        maps.event.addListener(map, 'idle', onIdle)
        detach = () => {
          maps.event.removeListener(map, 'dragstart', onDragStart)
          maps.event.removeListener(map, 'idle', onIdle)
        }

        mapRef.current = { maps, map }
        callbacks.current.onReady({
          // 지도 가운데는 2단계 시트 뒤에 숨는다. 검색창 아래 ~ 시트 윗변 사이 가운데로 오게 아래로 더 민다.
          // 넓은 화면은 지도 영역에 가리는 시트가 없어서 가운데 그대로다.
          panTo: (lat, lng) => {
            map.setCenter(new maps.LatLng(lat, lng))
            if (isDesktopNow()) return
            const h = window.innerHeight
            map.panBy(0, Math.round(h / 2 - (VISIBLE_TOP + h * 0.41) / 2))
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

  // 검색 결과 번호 원. 몇 개 안 되고 검색할 때마다 통째로 바뀌어서 매번 새로 그린다.
  useEffect(() => {
    const m = mapRef.current
    if (!ready || !m) return
    const overlays = results.map((r) => {
      const el = document.createElement('button')
      el.type = 'button'
      el.setAttribute('aria-label', `검색 결과 ${r.n}번`)
      el.textContent = String(r.n)
      const size = r.selected ? 30 : 24
      el.style.cssText = `width:${size}px;height:${size}px;border-radius:50%;border:2px solid #fff;font:700 12px/1 var(--font-sans);display:flex;align-items:center;justify-content:center;box-shadow:0 1px 4px rgba(20,22,31,.3);cursor:pointer;${
        r.selected ? 'background:var(--brand-600);color:#fff' : 'background:#fff;color:var(--brand-600);border-color:var(--brand-600)'
      }`
      el.addEventListener('click', r.onClick)
      const overlay = new m.maps.CustomOverlay({ position: new m.maps.LatLng(r.lat, r.lng), content: el, clickable: true, zIndex: 5 })
      overlay.setMap(m.map)
      return overlay
    })
    return () => overlays.forEach((o) => o.setMap(null))
  }, [results, ready])

  // 동선(Figma 7절): brand-600 4px 직선, 순서 번호는 골드 + 갈색 숫자, 구간 "약 N분" 흰 알약.
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
      const line = new maps.Polyline({
        path: r.stops.map((s) => new maps.LatLng(s.lat, s.lng)),
        strokeWeight: 4,
        strokeColor: getComputedStyle(document.documentElement).getPropertyValue('--brand-600').trim() || '#2A57C4',
        strokeOpacity: 1,
      })
      line.setMap(map)
      drawn.push(line)
      for (const s of r.stops) {
        const el = document.createElement('span')
        el.textContent = String(s.n)
        el.style.cssText =
          'display:flex;width:18px;height:18px;align-items:center;justify-content:center;border-radius:50%;background:var(--pin-confirmed);color:var(--pin-confirmed-mark);border:2px solid #fff;font:700 11px/1 var(--font-sans);transform:translate(14px,-34px)'
        overlay(s.lat, s.lng, el)
      }
      for (const l of r.legs) {
        const el = document.createElement('span')
        el.textContent = l.label
        el.style.cssText =
          'padding:2px 8px;border-radius:999px;background:#fff;border:1px solid var(--brand-600);color:var(--brand-700);font:700 11px/1.4 var(--font-sans);white-space:nowrap'
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
              <p className="text-sm text-warn-text">지도를 불러오지 못했어요</p>
              <p className="text-xs text-ink-500">
                {error instanceof KakaoMapKeyMissingError
                  ? 'frontend/.env.local 에 VITE_KAKAO_MAP_KEY 를 넣어주세요 (.env.example 참고)'
                  : error.message}
              </p>
              <p className="text-xs text-ink-500">핀 {pins.length}개는 아래 목록에 그대로 있어요</p>
            </>
          ) : (
            <p className="text-sm text-ink-500">지도를 불러오는 중…</p>
          )}
        </div>
      )}
    </div>
  )
}
