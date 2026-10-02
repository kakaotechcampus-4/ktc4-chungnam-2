import { useEffect, useLayoutEffect, useRef, useState } from 'react'

import { KakaoMapKeyMissingError, loadKakaoMaps } from './kakaoMap'
import { createMarkerLayer, type MarkerLayer } from './markerLayer'
import type { Pin } from './model'

/** 핀이 하나라도 있으면 곧바로 bounds 로 덮어쓴다. 빈 지도에서만 보이는 값이다(v1 장소 데이터는 서울). */
const FALLBACK_CENTER = { lat: 37.5665, lng: 126.978 }

/** 지도 버튼(현재 위치·최근 핀·전체 핀)이 지도를 움직이는 통로. */
export type MapController = {
  panTo: (lat: number, lng: number) => void
  fitPins: (pins: Pin[]) => void
}

/**
 * 화면 전체를 덮는 지도. 탭을 바꿔도 다시 만들지 않으려고 MapLayout 에 한 번만 둔다.
 * 마커는 React 바깥(markerLayer)에서 산다 — frontend/CLAUDE.md.
 */
export default function MapCanvas({
  pins,
  memberCount,
  onSelect,
  onReady,
  onMovingChange,
}: {
  pins: Pin[]
  /** 핀 색(참여율)의 분모 — 지도 전체 구성원 수. */
  memberCount: number
  onSelect: (pinId: string) => void
  onReady: (controller: MapController) => void
  /** 사용자가 지도를 끌기 시작하면 true, 멈추면 false. */
  onMovingChange: (moving: boolean) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const layerRef = useRef<MarkerLayer | null>(null)
  // 콜백이 바뀔 때마다 지도를 다시 만들면 깜빡인다. 최신 참조만 갈아끼운다.
  const callbacks = useRef({ onSelect, onReady, onMovingChange })
  useLayoutEffect(() => {
    callbacks.current = { onSelect, onReady, onMovingChange }
  })
  const fittedRef = useRef(false)
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

        callbacks.current.onReady({
          panTo: (lat, lng) => map.panTo(new maps.LatLng(lat, lng)),
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
      layer.fit(pins)
      fittedRef.current = true
    }
  }, [pins, memberCount, ready])

  return (
    <div className="fixed inset-0 bg-ink-100">
      <div ref={containerRef} className="h-full w-full" />
      {!ready && (
        <div className="absolute inset-x-0 top-32 flex flex-col items-center gap-1 px-4 text-center">
          {error ? (
            <>
              <p className="text-sm text-danger">지도를 불러오지 못했어요</p>
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
