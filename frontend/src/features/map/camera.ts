/**
 * 지도가 스스로 움직일 때의 계산(#1026, 멘토 리뷰 #816). 카카오 SDK 없이 화면 픽셀만 다뤄서 테스트한다.
 * 실제로 옮기고 확대하는 일은 MapCanvas 가 이 결과로 한다.
 *
 * 카카오 레벨은 작을수록 가깝고, 한 단계 멀어지면 같은 거리가 화면에서 반이 된다.
 * setBounds 는 움직임 없이 순간 맞추고, setLevel 은 레벨 차이 2 이하에서만 움직임을 보여 준다(카카오 문서).
 * 그래서 맞추기를 직접 계산해 옮기기와 2단계씩의 확대·축소로 나눠 보여 준다 — 축척이 한꺼번에 바뀌면
 * 무슨 일이 일어났는지 알아볼 수 없다.
 */

import type { MapHeading } from '@/features/shell/sheetStore'

/** 로드맵 레벨 범위. */
export const MIN_LEVEL = 1
export const MAX_LEVEL = 14
/** 한 번에 움직임을 보여 줄 수 있는 레벨 차이(카카오 setLevel animate 조건). */
export const ZOOM_STEP = 2

export type Px = { x: number; y: number }
export type Size = { w: number; h: number }
/** 지도 틀 안에서 비켜야 하는 여백(px) — 위는 검색창·칩, 아래는 시트처럼 지도를 가리는 것. */
export type Padding = { top: number; right: number; bottom: number; left: number }

/**
 * 넓은 화면에서 지도 왼쪽을 가리는 패널 카드 폭(px, #1538). 지도는 화면 전체이고 패널이 그 위에 떠 있다.
 * ponytail: 지도(MapCanvas)가 화면에 하나라 모듈 값 하나로 둔다. 지도를 둘 띄우게 되면 지도마다 넘긴다.
 */
export const view = { cover: 0 }

/**
 * 점을 맞출 때 비키는 여백. 넓은 화면은 지도 영역에 시트가 없어서 위는 칩, 오른쪽은 지도 버튼, 왼쪽은 패널 카드를 비킨다(#338, #1538).
 * 휴대폰은 위가 검색창·칩, 아래가 2단계 시트다.
 */
export function fitPadding(viewportH: number, desktop: boolean): Padding {
  return desktop
    ? { top: 64, right: 76, bottom: 32, left: 32 + view.cover }
    : { top: 170, right: 64, bottom: Math.round(viewportH * 0.62), left: 32 }
}

const clamp = (level: number) => Math.min(MAX_LEVEL, Math.max(MIN_LEVEL, level))

function extent(points: Px[]) {
  const xs = points.map((p) => p.x)
  const ys = points.map((p) => p.y)
  return { minX: Math.min(...xs), maxX: Math.max(...xs), minY: Math.min(...ys), maxY: Math.max(...ys) }
}

/** 점이 모두 여백 안 상자에 들어 있다 — 이미 보이니 옮길 필요가 없다. */
export function allInside(points: Px[], size: Size, pad: Padding): boolean {
  return points.every((p) => p.x >= pad.left && p.x <= size.w - pad.right && p.y >= pad.top && p.y <= size.h - pad.bottom)
}

/**
 * 점 전체가 여백 안에 들어오는 가장 가까운 레벨. `closest` 보다 가까이 가지 않는다 — 점이 하나이거나 몰려 있을 때
 * 골목 하나만 보이게 확 들어가지 않게.
 */
export function fitLevel(points: Px[], size: Size, pad: Padding, level: number, closest: number): number {
  const { minX, maxX, minY, maxY } = extent(points)
  const availW = size.w - pad.left - pad.right
  const availH = size.h - pad.top - pad.bottom
  if (availW <= 0 || availH <= 0) return level
  const ratio = Math.max((maxX - minX) / availW, (maxY - minY) / availH)
  if (ratio === 0) return clamp(Math.max(closest, MIN_LEVEL))
  // 레벨이 하나 오르면 화면 거리가 반이다 → 지금보다 log2(ratio) 단계 멀어지면 꼭 맞는다. 소수점 오차로 한 단계 더 멀어지지 않게 조금 깎는다.
  return clamp(Math.max(closest, Math.ceil(level + Math.log2(ratio) - 1e-9)))
}

/**
 * 맞춘 뒤 지도 가운데가 될 자리(지금 레벨의 화면 px). 점 범위의 가운데가 여백 안 상자의 가운데에 오게 한다.
 * 목표 레벨의 1px 은 지금 레벨의 2^(목표−지금) px 이다.
 */
export function fitCenter(points: Px[], size: Size, pad: Padding, level: number, target: number): Px {
  const { minX, maxX, minY, maxY } = extent(points)
  const scale = 2 ** (target - level)
  const boxX = (pad.left + size.w - pad.right) / 2
  const boxY = (pad.top + size.h - pad.bottom) / 2
  return { x: (minX + maxX) / 2 + (size.w / 2 - boxX) * scale, y: (minY + maxY) / 2 + (size.h / 2 - boxY) * scale }
}

/** from → to 사이를 ZOOM_STEP 씩 나눈 레벨(시작은 빼고 끝은 넣는다). 같으면 빈 목록. */
export function zoomSteps(from: number, to: number): number[] {
  const steps: number[] = []
  const dir = Math.sign(to - from)
  for (let l = from; l !== to; ) {
    l = Math.abs(to - l) <= ZOOM_STEP ? to : l + dir * ZOOM_STEP
    steps.push(l)
  }
  return steps
}

/**
 * 화면에서 서로 `dist` px 안에 있는 점끼리 묶는다(#1174). 묶음은 목록 순서대로, 묶음 안도 들어온 순서다.
 * 점마다 앞에서 만든 묶음의 첫 점과만 잰다 — 검색 결과는 몇 곳뿐이라 이 정도로 충분하다.
 */
export function groupNear(points: Px[], dist: number): number[][] {
  const groups: number[][] = []
  points.forEach((p, i) => {
    const g = groups.find((g) => Math.hypot(points[g[0]].x - p.x, points[g[0]].y - p.y) < dist)
    if (g) g.push(i)
    else groups.push([i])
  })
  return groups
}

/** 8방향의 화면 각도(°, 오른쪽 0에서 시계 방향 — 화면 y 는 아래가 +). */
const HEADING_DEG: Record<MapHeading, number> = {
  right: 0,
  'down-right': 45,
  down: 90,
  'down-left': 135,
  left: 180,
  'up-left': -135,
  up: -90,
  'up-right': -45,
}
const HEADINGS = Object.keys(HEADING_DEG) as MapHeading[]

/** 이만큼(px) 끌어야 방향을 정한다. 이보다 짧으면 손떨림 1~2px 에도 대각선으로 튄다(#1746). */
export const WALK_MIN_PX = 12
/** 지금 방향의 칸(±22.5°)에서 이만큼(°) 더 벗어나야 바꾼다 — 경계에서 두 방향을 오가지 않게. */
const WALK_KEEP_DEG = 15

/**
 * 지도 위 핑고가 걷는 쪽(#1433, #1746) — 화면이 가는 쪽, 곧 지도를 끈 쪽의 반대다.
 * 땅(지도)이 발밑으로 끈 쪽으로 지나가니, 핑고는 그 반대로 걸어 나가는 것처럼 보인다.
 * drag 는 끈 만큼(px). min px 보다 덜 움직였으면 정하지 않는다(null).
 * prev(지금 방향)의 칸에서 WALK_KEEP_DEG 안이면 prev 를 그대로 둔다 — 떨림이나 손 뗄 때의 작은 꺾임에 바뀌지 않는다.
 */
export function walkHeading(drag: Px, prev: MapHeading | null, min = WALK_MIN_PX): MapHeading | null {
  if (Math.hypot(drag.x, drag.y) < min) return null
  const deg = (Math.atan2(-drag.y, -drag.x) * 180) / Math.PI
  const off = (h: MapHeading) => Math.abs(((deg - HEADING_DEG[h] + 540) % 360) - 180)
  if (prev && off(prev) <= 22.5 + WALK_KEEP_DEG) return prev
  return HEADINGS.reduce((best, h) => (off(h) < off(best) ? h : best))
}
