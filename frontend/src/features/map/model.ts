import type { components } from '@pingo/contracts/src/types/api'

export type PinDto = components['schemas']['Pin']
/** 지금은 응답 그대로다. 화면용으로 바꿀 게 생기면(반응 집계 등) 여기서 바꾸고 화면은 그대로 둔다. */
export type Pin = PinDto

export type PinCategory = Pin['category']
export type ReactionType = 'like' | 'neutral' | 'against'

/** v1에 핀으로 만들 수 있는 카테고리만 칩으로 둔다 — 숙소·기타는 핀을 만들 수 없다(#191). */
export const FILTER_CATEGORIES: PinCategory[] = ['음식점', '카페', '관광지']

export const SORTS = {
  most: '의견 많은 순',
  least: '의견 적은 순',
  recent: '최근 추가 순',
} as const
export type PinSort = keyof typeof SORTS

export type PinFilters = { category: PinCategory | null; createdBy: string | null; sort: PinSort }

/** ♥·△·🚫 중 하나라도 남긴 사람 수. 한 사람은 한 핀에 반응 하나만 남긴다. */
export function participants(pin: Pin): number {
  const s = pin.reaction_summary
  return s.like + s.neutral + s.against
}

/**
 * 핀 색의 참여율(docs/design/colors.md 3절). 분모는 지도 전체 구성원 수, 구성원 수만큼 끊는다.
 * 구성원 수를 아직 모르면 0으로 본다 — 0% 핀도 테두리로 또렷하다.
 */
export function participationRatio(pin: Pin, memberCount: number): number {
  if (memberCount <= 0) return 0
  return Math.min(1, participants(pin) / memberCount)
}

export function filterPins(pins: Pin[], f: PinFilters): Pin[] {
  const kept = pins.filter(
    (p) => (!f.category || p.category === f.category) && (!f.createdBy || p.created_by === f.createdBy),
  )
  if (f.sort === 'recent') {
    // ponytail: 핀 응답에 만든 시각이 없어 서버가 준 순서의 역순을 최근 순으로 본다. created_at 이 생기면 그 값으로.
    return kept.reverse()
  }
  const dir = f.sort === 'most' ? -1 : 1
  // 같은 참여 수면 원래 순서를 지킨다(Array.prototype.sort 는 안정 정렬).
  return kept.sort((a, b) => dir * (participants(a) - participants(b)))
}

export type PinCardView = {
  id: string
  name: string
  meta: string
  counts: Record<ReactionType | 'unknown', number>
  mine: ReactionType | null
}

/** 카드 한 장. 미확인(?)은 구성원 수에서 반응한 사람을 뺀 값이다. */
export function toPinCard(pin: Pin, memberCount: number): PinCardView {
  const s = pin.reaction_summary
  return {
    id: pin.id,
    name: pin.place_name ?? '이름 없는 장소',
    meta: [pin.category, pin.created_by_display_name && `${pin.created_by_display_name}님이 찍음`].filter(Boolean).join(' · '),
    counts: { ...s, unknown: Math.max(0, memberCount - participants(pin)) },
    mine: pin.my_reaction?.type ?? null,
  }
}
