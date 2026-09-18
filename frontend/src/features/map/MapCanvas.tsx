import type { Pin } from './usePins'

/**
 * 카카오맵 캔버스 + 마커 (#20).
 * 지금은 자리만 잡아둔다 — SDK 로딩·마커 레이어는 #20 에서 이 파일과 형제 모듈이 맡는다.
 */
export default function MapCanvas({ pins }: { pins: Pin[] }) {
  return (
    <div className="mb-4 flex h-40 items-center justify-center rounded-lg border border-dashed text-sm text-muted-foreground">
      지도 자리 (#20) · 핀 {pins.length}개
    </div>
  )
}
