import { useEffect, useRef, useState } from 'react'

import { KakaoMapKeyMissingError, loadKakaoMaps } from './kakaoMap'
import { createMarkerLayer, type MarkerLayer } from './markerLayer'
import type { Pin } from './usePins'

/** 핀이 하나라도 있으면 곧바로 bounds 로 덮어쓴다. 빈 지도에서만 보이는 값이다. */
const FALLBACK_CENTER = { lat: 33.4996, lng: 126.5312 }

export default function MapCanvas({
  pins,
  onSelect,
}: {
  pins: Pin[]
  onSelect: (pinId: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const layerRef = useRef<MarkerLayer | null>(null)
  const onSelectRef = useRef(onSelect)
  const fittedRef = useRef(false)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<Error | null>(null)

  // 콜백이 바뀔 때마다 지도를 다시 만들면 깜빡인다. 최신 참조만 갈아끼운다.
  useEffect(() => {
    onSelectRef.current = onSelect
  }, [onSelect])

  useEffect(() => {
    let cancelled = false

    loadKakaoMaps()
      .then((maps) => {
        if (cancelled || !containerRef.current) return
        const map = new maps.Map(containerRef.current, {
          center: new maps.LatLng(FALLBACK_CENTER.lat, FALLBACK_CENTER.lng),
          level: 5,
        })
        layerRef.current = createMarkerLayer(maps, map, (pinId) => onSelectRef.current(pinId))
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
      layerRef.current?.destroy()
      layerRef.current = null
    }
  }, [])

  useEffect(() => {
    const layer = layerRef.current
    if (!ready || !layer) return

    layer.sync(pins)

    // 처음 핀이 들어왔을 때만 시야를 맞춘다. 매번 하면 사용자가 옮긴 시야를 뺏는다.
    if (!fittedRef.current && pins.length > 0) {
      layer.fit(pins)
      fittedRef.current = true
    }
  }, [pins, ready])

  if (error) {
    return (
      <div className="mb-4 flex h-64 flex-col items-center justify-center gap-1 rounded-lg border border-dashed p-4 text-center">
        <p className="text-sm text-destructive">지도를 불러오지 못했어요</p>
        <p className="text-xs text-muted-foreground">
          {error instanceof KakaoMapKeyMissingError
            ? 'frontend/.env.local 에 VITE_KAKAO_MAP_KEY 를 넣어주세요 (.env.example 참고)'
            : error.message}
        </p>
        <p className="text-xs text-muted-foreground">핀 {pins.length}개는 아래 목록에 그대로 있어요</p>
      </div>
    )
  }

  return (
    <div className="relative mb-4 h-64 overflow-hidden rounded-lg border">
      <div ref={containerRef} className="h-full w-full" />
      {!ready && (
        <p className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
          지도를 불러오는 중…
        </p>
      )}
    </div>
  )
}
