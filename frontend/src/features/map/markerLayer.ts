import { isDesktopNow } from '@/features/shell/useIsDesktop'

import { createPinMarkerElement } from './pinMarker'
import { isPlaced, participationRatio, type Pin, type PlacedPin } from './model'

export interface MarkerLayer {
  /** 들어온 목록과 지금 떠 있는 마커를 비교해 추가·삭제만 한다. 구성원 수는 핀 색(참여율)의 분모다. */
  sync(pins: Pin[], memberCount: number): void
  /** 상세를 연 핀을 크게·맨 위로·이름과 함께 보여 준다. null 이면 해제. */
  select(pinId: string | null): void
  /** 점(핀·검색 결과) 전체가 들어오도록 시야를 맞춘다. */
  fit(points: { lat: number; lng: number }[]): void
  destroy(): void
}

type Placed = PlacedPin

/** 이 값이 그대로면 오버레이를 다시 만들 이유가 없다. */
function signature(pin: Placed, ratio: number): string {
  return [pin.kind, pin.lat, pin.lng, pin.place_name, ratio].join('|')
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
  const names = new Map<string, string>()
  const elements = new Map<string, HTMLElement>()
  let selected: string | null = null

  /** 지도 위에서 어느 핀을 보고 있는지 보이게 한다(#308). 다시 그려진 마커에도 다시 건다. */
  function mark(pinId: string, on: boolean) {
    const overlay = overlays.get(pinId)
    const el = elements.get(pinId)
    if (!overlay || !el) return
    overlay.setZIndex(on ? 10 : 0)
    const svg = el.querySelector('svg')
    if (svg) {
      svg.style.transformOrigin = '50% 100%'
      svg.style.transform = on ? 'scale(1.25)' : ''
      svg.style.filter = on ? 'drop-shadow(0 0 2px #fff) drop-shadow(0 0 2px #fff)' : ''
    }
    el.querySelector('[data-pin-name]')?.remove()
    if (on) {
      const label = document.createElement('span')
      label.dataset.pinName = ''
      // 이름은 textContent 로만 넣는다(마크업으로 해석되지 않게).
      label.textContent = names.get(pinId) ?? ''
      label.setAttribute('aria-hidden', 'true')
      label.style.cssText =
        'position:absolute;top:100%;left:50%;transform:translateX(-50%);margin-top:4px;padding:2px 8px;border-radius:8px;' +
        'background:#fff;color:var(--ink-900);font-size:0.75rem;font-weight:700;line-height:1.4;white-space:nowrap;box-shadow:0 1px 4px rgba(20,22,31,.18)'
      el.style.position = 'relative'
      el.appendChild(label)
    }
  }

  function drop(pinId: string) {
    overlays.get(pinId)?.setMap(null)
    overlays.delete(pinId)
    signatures.delete(pinId)
    names.delete(pinId)
    elements.delete(pinId)
  }

  return {
    sync(pins, memberCount) {
      const alive = new Set<string>()

      for (const pin of pins) {
        if (!isPlaced(pin)) continue
        alive.add(pin.id)

        const ratio = participationRatio(pin, memberCount)
        const sig = signature(pin, ratio)
        if (signatures.get(pin.id) === sig) continue

        drop(pin.id)
        const el = createPinMarkerElement(pin, ratio, () => onSelect(pin.id))
        const overlay = new maps.CustomOverlay({
          position: new maps.LatLng(pin.lat, pin.lng),
          content: el,
          yAnchor: 1,
          clickable: true,
        })
        overlay.setMap(map)
        overlays.set(pin.id, overlay)
        signatures.set(pin.id, sig)
        names.set(pin.id, pin.place_name ?? '')
        elements.set(pin.id, el)
        if (pin.id === selected) mark(pin.id, true)
      }

      for (const pinId of [...overlays.keys()]) {
        if (!alive.has(pinId)) drop(pinId)
      }
    },

    select(pinId) {
      if (selected) mark(selected, false)
      selected = pinId
      if (pinId) mark(pinId, true)
    },

    fit(points) {
      const bounds = new maps.LatLngBounds()
      let placed = 0
      for (const p of points) {
        bounds.extend(new maps.LatLng(p.lat, p.lng))
        placed += 1
      }
      if (placed === 0) return
      // 넓은 화면은 지도 영역에 시트가 없다. 위는 칩, 오른쪽은 지도 버튼만 비킨다(#338).
      if (isDesktopNow()) return map.setBounds(bounds, 64, 76, 32, 32)
      // 위는 검색창·칩, 아래는 2단계 시트가 덮는다. 그 바깥에 핀이 오도록 여백을 둔다.
      map.setBounds(bounds, 170, 64, Math.round(window.innerHeight * 0.62), 32)
    },

    destroy() {
      for (const pinId of [...overlays.keys()]) drop(pinId)
    },
  }
}
