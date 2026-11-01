import { isDesktopNow } from '@/features/shell/useIsDesktop'

import { createPinMarkerElement, markSelected, setPinLabel, showPinLabel } from './pinMarker'
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

/**
 * 방금 생긴 핀만 떨어지며 나타난다(#595). 처음 지도를 열 때·칩을 바꿀 때 나타나는 핀은 오래전에 생겨서 움직이지 않는다.
 * ponytail: 기기 시계로 잰다 — 시계가 서버와 10초 넘게 어긋나면 효과가 안 날 뿐이다. 필요하면 sync 에 "새 핀 id"를 넘긴다.
 */
const FRESH_MS = 10_000

/**
 * 이름표는 이 레벨까지만 보인다(작을수록 가깝다). 더 멀리 보면 동네 단위라 이름이 읽히지 않아 고른 핀만 남긴다.
 * 그보다 가까울 때 핀이 몰리면 겹침 정리(relabel)가 덜 중요한 이름표를 숨긴다.
 */
export const LABEL_MAX_LEVEL = 8

/**
 * 바탕 지도를 얼마나 옅게 할지(0 그대로 ~ 1 가장 옅게). 바탕의 가게 표시가 핀과 뒤엉키는 건 가까이 볼 때라,
 * 이름표가 뜨기 시작하는 레벨(LABEL_MAX_LEVEL)부터 옅어지기 시작해 FADE_STEPS 레벨 더 들어가면 가장 옅다.
 */
const FADE_STEPS = 4
export function mapFade(level: number): number {
  return Math.min(1, Math.max(0, (LABEL_MAX_LEVEL + 1 - level) / FADE_STEPS))
}

/** 핀 몸통 크기(px, pinMarker 의 svg 30×38). 이름표가 다른 핀을 덮지 않게 비킨다. */
const BODY = { w: 30, h: 38 }
/** 이름표 높이(px)와 핀 끝에서 떨어진 거리. 폭은 그려진 이름표에서 잰다. */
const LABEL = { h: 20, gap: 4 }

type Box = { l: number; t: number; r: number; b: number }
const overlaps = (a: Box, b: Box) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b

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
  /** 이름표와 겹침 정리 순서에 쓰는 값. */
  const info = new Map<string, { name: string; lat: number; lng: number; confirmed: boolean; ratio: number; created: number }>()
  const elements = new Map<string, HTMLElement>()
  /** 한 번 떨어진 핀. 의견이 달려 마커를 다시 그려도 또 떨어지지 않게 한다. */
  const dropped = new Set<string>()
  let selected: string | null = null

  /** 지도 위에서 어느 핀을 보고 있는지 보이게 한다(#308). 다시 그려진 마커에도 다시 건다. */
  function mark(pinId: string, on: boolean) {
    const overlay = overlays.get(pinId)
    const el = elements.get(pinId)
    if (!overlay || !el) return
    overlay.setZIndex(on ? 10 : 0)
    const name = info.get(pinId)?.name ?? ''
    markSelected(el, name, on)
    if (!on) setPinLabel(el, name, 'quiet')
  }

  /**
   * 지도에 찍힌 핀은 누르지 않아도 이름이 보인다. 다만 이름표끼리, 또는 이름표가 다른 핀을 덮으면 덜 중요한 쪽을 숨긴다.
   * 순서: 고른 핀 → 확정 → 참여율 높은 순 → 먼저 찍은 순. 멀리 보면(LABEL_MAX_LEVEL 초과) 고른 핀만 남긴다.
   * 옮기거나 확대가 끝날 때(idle)마다 다시 정한다 — 핀은 많아야 수십 개다.
   */
  function relabel() {
    if (elements.size === 0) return
    const far = map.getLevel() > LABEL_MAX_LEVEL
    const proj = map.getProjection()
    const at = new Map<string, { x: number; y: number }>()
    for (const [id, p] of info) at.set(id, proj.containerPointFromCoords(new maps.LatLng(p.lat, p.lng)))
    const bodies = [...at].map(([id, { x, y }]) => ({ id, box: { l: x - BODY.w / 2, t: y - BODY.h, r: x + BODY.w / 2, b: y } }))

    const order = [...info.keys()].sort((a, b) => {
      const pa = info.get(a)!
      const pb = info.get(b)!
      return (
        Number(b === selected) - Number(a === selected) ||
        Number(pb.confirmed) - Number(pa.confirmed) ||
        pb.ratio - pa.ratio ||
        pa.created - pb.created
      )
    })
    const shown: Box[] = []
    for (const id of order) {
      const el = elements.get(id)
      const p = at.get(id)
      if (!el || !p) continue
      const label = el.querySelector<HTMLElement>('[data-pin-name]')
      if (!label) continue
      // 그려지기 전(지도 밖)이면 폭이 0이라 글자 수로 어림한다.
      const w = label.offsetWidth || Math.min(info.get(id)!.name.length, 8) * 12 + 16
      const box = { l: p.x - w / 2, t: p.y + LABEL.gap, r: p.x + w / 2, b: p.y + LABEL.gap + LABEL.h }
      // 고른 핀은 언제나 보이고, 그 자리를 먼저 차지한다.
      const free =
        id === selected || (!far && !shown.some((s) => overlaps(s, box)) && !bodies.some((o) => o.id !== id && overlaps(o.box, box)))
      showPinLabel(el, free)
      if (free) shown.push(box)
    }
  }
  maps.event.addListener(map, 'idle', relabel)

  function drop(pinId: string) {
    overlays.get(pinId)?.setMap(null)
    overlays.delete(pinId)
    signatures.delete(pinId)
    info.delete(pinId)
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
        if (!dropped.has(pin.id) && Math.abs(Date.now() - Date.parse(pin.created_at)) < FRESH_MS) {
          dropped.add(pin.id)
          el.classList.add('enter-drop')
          // 지도가 마커를 다시 붙여도 재생되지 않게 끝나면 뗀다.
          el.addEventListener('animationend', () => el.classList.remove('enter-drop'), { once: true })
        }
        const overlay = new maps.CustomOverlay({
          position: new maps.LatLng(pin.lat, pin.lng),
          content: el,
          yAnchor: 1,
          clickable: true,
        })
        overlay.setMap(map)
        overlays.set(pin.id, overlay)
        signatures.set(pin.id, sig)
        const name = pin.place_name ?? ''
        info.set(pin.id, { name, lat: pin.lat, lng: pin.lng, confirmed: pin.kind === '확정', ratio, created: Date.parse(pin.created_at) })
        elements.set(pin.id, el)
        setPinLabel(el, name, 'quiet')
        if (pin.id === selected) mark(pin.id, true)
      }

      for (const pinId of [...overlays.keys()]) {
        if (!alive.has(pinId)) drop(pinId)
      }
      relabel()
    },

    select(pinId) {
      if (selected) mark(selected, false)
      selected = pinId
      if (pinId) mark(pinId, true)
      relabel()
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
      maps.event.removeListener(map, 'idle', relabel)
      for (const pinId of [...overlays.keys()]) drop(pinId)
    },
  }
}
