import { isDesktopNow } from '@/features/shell/useIsDesktop'

import { fitPadding, groupNear } from './camera'
import { attachTrashDrag } from './pinDrag'
import { createPinGroupMarkerElement, createPinMarkerElement, markSelected, PIN_LABEL, setPinLabel, showPinLabel } from './pinMarker'
import { isPlaced, participationRatio, type Pin, type PlacedPin } from './model'

export interface MarkerLayer {
  /**
   * 들어온 목록과 지금 떠 있는 마커를 비교해 추가·삭제만 한다. 구성원 수는 핀 색(참여율)의 분모다.
   * fresh 는 마지막으로 본 뒤 새 핀·의견이 있는 핀 id(#1454) — 귤색 점을 단다.
   */
  sync(pins: Pin[], memberCount: number, fresh?: ReadonlySet<string>): void
  /** 상세를 연 핀을 크게·맨 위로·이름과 함께 보여 준다. null 이면 해제. */
  select(pinId: string | null): void
  /** 점 전체가 들어오도록 시야를 바로 맞춘다(지도를 처음 열 때). */
  fit(points: { lat: number; lng: number }[]): void
  /**
   * 지도 핀보다 먼저 자리를 잡는 이름표 — AI 추천 탭의 AI 후보(#1744). 지도 핀과 한 번에 겹침을 정리해,
   * 후보 이름표와 지도 핀 이름표가 서로를 덮지 않는다. 화면 좌표가 지도 움직임 따라 바뀌어 정리할 때마다 부른다.
   */
  setLeadLabels(get: () => LabelItem[]): void
  destroy(): void
}

/** 겹침 정리에 넘기는 이름표 하나. x·y 는 핀 끝의 화면 좌표, keep 은 고른 핀이다. */
export type LabelItem = { id: string; el: HTMLElement; name: string; x: number; y: number; keep: boolean }

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
/**
 * 핀 끝(좌표)끼리 이만큼(px)보다 가까우면 숫자 핀 하나로 묶는다(#1576) — 핀 머리(지름 약 20)가 서로 덮이기 시작하는 거리다.
 * 확대할수록 화면 거리가 벌어져 묶음이 풀린다. MapCanvas 가 「확대로 풀리는지」를 잴 때도 이 값을 쓴다.
 */
export const PIN_GROUP_PX = 24

type Box = { l: number; t: number; r: number; b: number }
const overlaps = (a: Box, b: Box) => a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b
/** 핀 끝(화면 좌표)에서 핀 몸통 상자. */
const bodyBox = ({ x, y }: { x: number; y: number }): Box => ({ l: x - BODY.w / 2, t: y - BODY.h, r: x + BODY.w / 2, b: y })

/**
 * 이름표를 겹치지 않게 남긴다 — 지도 핀과 AI 후보(setLeadLabels)를 한 번에 정리한다.
 * items 를 중요한 순서로 받아, 앞서 남긴 이름표나 다른 핀 몸통(bodies)을 덮지 않는 것만 남긴다.
 * keep(고른 핀)은 언제나 남고 그 자리를 먼저 차지한다. 멀리 보면(far) keep 만 남는다. x·y 는 핀 끝의 화면 좌표다.
 */
export function placeLabels(
  items: LabelItem[],
  bodies: { id: string; x: number; y: number }[],
  far: boolean,
) {
  const shown: Box[] = []
  for (const it of items) {
    const label = it.el.querySelector<HTMLElement>('[data-pin-name]')
    if (!label) continue
    // 그려지기 전(지도 밖)이면 폭이 0이라 글자 수로 어림한다.
    const w = label.offsetWidth || Math.min(it.name.length, 8) * 12 + 16
    const box = { l: it.x - w / 2, t: it.y + PIN_LABEL.gap, r: it.x + w / 2, b: it.y + PIN_LABEL.gap + PIN_LABEL.h }
    const free =
      it.keep || (!far && !shown.some((s) => overlaps(s, box)) && !bodies.some((o) => o.id !== it.id && overlaps(bodyBox(o), box)))
    showPinLabel(it.el, free)
    if (free) shown.push(box)
  }
}

/** 이 값이 그대로면 오버레이를 다시 만들 이유가 없다. */
function signature(pin: Placed, ratio: number, fresh: boolean): string {
  return [pin.kind, pin.lat, pin.lng, pin.place_name, ratio, fresh].join('|')
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
  /** 겹친 핀 묶음을 눌렀다(#1576). 좌표는 묶음 안 핀들이다. */
  onGroup: (pinIds: string[], points: { lat: number; lng: number }[]) => void,
): MarkerLayer {
  const overlays = new Map<string, kakao.maps.CustomOverlay>()
  const signatures = new Map<string, string>()
  /** 이름표와 겹침 정리 순서에 쓰는 값. */
  const info = new Map<string, { name: string; lat: number; lng: number; confirmed: boolean; ratio: number; created: number; fresh: boolean }>()
  const elements = new Map<string, HTMLElement>()
  /** 휴지통으로 끌기를 뗀다(#1012). 끄는 도중 마커가 다시 그려지면 끌기도 끝낸다. */
  const detachDrag = new Map<string, () => void>()
  /** 한 번 떨어진 핀. 의견이 달려 마커를 다시 그려도 또 떨어지지 않게 한다. */
  const dropped = new Set<string>()
  let selected: string | null = null
  let leadLabels: () => LabelItem[] = () => []
  /** 겹쳐서 묶음 핀 뒤로 숨은 핀(#1576). */
  const grouped = new Set<string>()
  let groups: { overlay: kakao.maps.CustomOverlay; lat: number; lng: number }[] = []
  let groupKey = ''

  /**
   * 화면에서 겹친 핀을 숫자 핀 하나로 묶는다(#1576). 고른 핀은 묶지 않는다 — 상세를 연 핀은 언제나 제 모양으로 보인다.
   * 겹침은 축척에만 달려서 확대·축소, 핀 목록, 고른 핀이 바뀔 때만 다시 묶고, 묶음이 그대로면 다시 그리지 않는다.
   */
  function regroup() {
    const proj = map.getProjection()
    const ids = [...info.keys()].filter((id) => id !== selected)
    const px = ids.map((id) => proj.containerPointFromCoords(new maps.LatLng(info.get(id)!.lat, info.get(id)!.lng)))
    const sets = groupNear(px, PIN_GROUP_PX)
      .filter((g) => g.length > 1)
      .map((g) => g.map((i) => ids[i]))
    grouped.clear()
    for (const id of sets.flat()) grouped.add(id)
    // hidden 으로 숨긴다(preflight 가 [hidden] 을 display:none !important 로 둔다). style.display 를 비우면
    // 핀 버튼의 display:flex(가운데 정렬)까지 지워져 핀 그림만 왼쪽 위로 붙고 이름표 꼬리가 핀 끝에서 어긋났다.
    for (const [id, el] of elements) el.hidden = grouped.has(id)
    const key = sets.map((g) => g.map((id) => `${id}:${signatures.get(id)}`).join(',')).join('|')
    if (key === groupKey) return
    groupKey = key
    for (const g of groups) g.overlay.setMap(null)
    groups = sets.map((g) => {
      const members = g.map((id) => info.get(id)!)
      const lat = members.reduce((sum, m) => sum + m.lat, 0) / members.length
      const lng = members.reduce((sum, m) => sum + m.lng, 0) / members.length
      const el = createPinGroupMarkerElement(
        {
          names: members.map((m) => m.name || '이름 없는 핀'),
          confirmed: members.every((m) => m.confirmed),
          ratio: Math.max(...members.map((m) => m.ratio)),
          fresh: members.some((m) => m.fresh),
        },
        () => onGroup(g, members.map(({ lat, lng }) => ({ lat, lng }))),
      )
      // 묶음은 낱개 핀 위에, 고른 핀(10) 아래에 둔다.
      const overlay = new maps.CustomOverlay({ position: new maps.LatLng(lat, lng), content: el, yAnchor: 1, clickable: true, zIndex: 5 })
      overlay.setMap(map)
      return { overlay, lat, lng }
    })
  }
  maps.event.addListener(map, 'zoom_changed', regroup)

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
    const lead = leadLabels()
    if (elements.size === 0 && lead.length === 0) return
    const far = map.getLevel() > LABEL_MAX_LEVEL
    const proj = map.getProjection()
    const at = new Map<string, { x: number; y: number }>()
    for (const [id, p] of info) if (!grouped.has(id)) at.set(id, proj.containerPointFromCoords(new maps.LatLng(p.lat, p.lng)))
    // 묶음 핀도 이름표가 덮으면 안 되는 몸통이다. 묶음 핀은 이름표가 없다 — 이름은 누르면 나오는 목록에 있다.
    const bodies = [
      ...[...at].map(([id, p]) => ({ id, x: p.x, y: p.y })),
      ...groups.map((g, i) => {
        const { x, y } = proj.containerPointFromCoords(new maps.LatLng(g.lat, g.lng))
        return { id: `group:${i}`, x, y }
      }),
    ]

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
    const items = order.flatMap((id) => {
      const el = elements.get(id)
      const p = at.get(id)
      return el && p ? [{ id, el, name: info.get(id)!.name, x: p.x, y: p.y, keep: id === selected }] : []
    })
    placeLabels([...lead, ...items], [...bodies, ...lead], far)
  }
  maps.event.addListener(map, 'idle', relabel)

  function drop(pinId: string) {
    detachDrag.get(pinId)?.()
    detachDrag.delete(pinId)
    overlays.get(pinId)?.setMap(null)
    overlays.delete(pinId)
    signatures.delete(pinId)
    info.delete(pinId)
    elements.delete(pinId)
  }

  return {
    sync(pins, memberCount, fresh) {
      const alive = new Set<string>()

      for (const pin of pins) {
        if (!isPlaced(pin)) continue
        alive.add(pin.id)

        const ratio = participationRatio(pin, memberCount)
        const isFresh = fresh?.has(pin.id) ?? false
        const sig = signature(pin, ratio, isFresh)
        if (signatures.get(pin.id) === sig) continue

        drop(pin.id)
        const el = createPinMarkerElement(pin, ratio, () => onSelect(pin.id), isFresh)
        // 찍은 사람·방장만 끌어서 휴지통에 버릴 수 있다. 끄는 그림은 이 마커의 핀 모양 그대로다.
        if (pin.permissions.can_delete) detachDrag.set(pin.id, attachTrashDrag(el, () => pin, () => el.querySelector('svg')?.outerHTML ?? ''))
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
        info.set(pin.id, { name, lat: pin.lat, lng: pin.lng, confirmed: pin.kind === '확정', ratio, created: Date.parse(pin.created_at), fresh: isFresh })
        elements.set(pin.id, el)
        setPinLabel(el, name, 'quiet')
        if (pin.id === selected) mark(pin.id, true)
      }

      for (const pinId of [...overlays.keys()]) {
        if (!alive.has(pinId)) drop(pinId)
      }
      regroup()
      relabel()
    },

    select(pinId) {
      if (selected) mark(selected, false)
      selected = pinId
      if (pinId) mark(pinId, true)
      regroup()
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
      // 지도를 처음 열 때만 쓴다 — 아직 본 화면이 없어서 바로 맞춘다. 그 뒤의 맞추기는 MapCanvas 가 나눠서 움직인다(#1026).
      const pad = fitPadding(window.innerHeight, isDesktopNow())
      map.setBounds(bounds, pad.top, pad.right, pad.bottom, pad.left)
    },

    setLeadLabels(get) {
      leadLabels = get
      relabel()
    },

    destroy() {
      maps.event.removeListener(map, 'idle', relabel)
      maps.event.removeListener(map, 'zoom_changed', regroup)
      for (const g of groups) g.overlay.setMap(null)
      for (const pinId of [...overlays.keys()]) drop(pinId)
    },
  }
}
