import { createPinMarkerElement } from './pinMarker'
import type { Pin } from './usePins'

export interface MarkerLayer {
  /** 들어온 목록과 지금 떠 있는 마커를 비교해 추가·삭제만 한다. */
  sync(pins: Pin[]): void
  /** 핀 전체가 들어오도록 시야를 맞춘다. */
  fit(pins: Pin[]): void
  destroy(): void
}

type Placed = Pin & { id: string; lat: number; lng: number }

/** 좌표 없는 핀은 지도에 올릴 수 없다. 목록에는 그대로 남으므로 조용히 버리는 게 아니다. */
function isPlaced(pin: Pin): pin is Placed {
  return typeof pin.id === 'string' && typeof pin.lat === 'number' && typeof pin.lng === 'number'
}

/** 이 값이 그대로면 오버레이를 다시 만들 이유가 없다. */
function signature(pin: Placed): string {
  return [pin.kind, pin.lat, pin.lng, pin.place_name].join('|')
}

/**
 * 마커는 React 렌더 트리 바깥에서 산다 (frontend/CLAUDE.md).
 *
 * 카카오맵 SDK 는 명령형이라 React 가 다시 그릴 때마다 오버레이를 새로 만들면
 * 지도가 깜빡이고 열려 있던 상세가 닫힌다. 그래서 pinId → 오버레이 맵을 들고 있다가
 * 실제로 바뀐 핀만 갈아끼운다.
 */
export function createMarkerLayer(
  maps: typeof kakao.maps,
  map: kakao.maps.Map,
  onSelect: (pinId: string) => void,
): MarkerLayer {
  const overlays = new Map<string, kakao.maps.CustomOverlay>()
  const signatures = new Map<string, string>()

  function drop(pinId: string) {
    overlays.get(pinId)?.setMap(null)
    overlays.delete(pinId)
    signatures.delete(pinId)
  }

  return {
    sync(pins) {
      const alive = new Set<string>()

      for (const pin of pins) {
        if (!isPlaced(pin)) continue
        alive.add(pin.id)

        const sig = signature(pin)
        if (signatures.get(pin.id) === sig) continue

        drop(pin.id)
        const overlay = new maps.CustomOverlay({
          position: new maps.LatLng(pin.lat, pin.lng),
          content: createPinMarkerElement(pin, () => onSelect(pin.id)),
          yAnchor: 1,
          clickable: true,
        })
        overlay.setMap(map)
        overlays.set(pin.id, overlay)
        signatures.set(pin.id, sig)
      }

      for (const pinId of [...overlays.keys()]) {
        if (!alive.has(pinId)) drop(pinId)
      }
    },

    fit(pins) {
      const bounds = new maps.LatLngBounds()
      let placed = 0
      for (const pin of pins) {
        if (!isPlaced(pin)) continue
        bounds.extend(new maps.LatLng(pin.lat, pin.lng))
        placed += 1
      }
      if (placed > 0) map.setBounds(bounds)
    },

    destroy() {
      for (const pinId of [...overlays.keys()]) drop(pinId)
    },
  }
}
