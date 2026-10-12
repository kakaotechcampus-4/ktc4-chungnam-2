import type { components } from '@pingo/contracts/src/types/api'

export type PinDto = components['schemas']['Pin']
/** 지금은 응답 그대로다. 화면용으로 바꿀 게 생기면(반응 집계 등) 여기서 바꾸고 화면은 그대로 둔다. */
export type Pin = PinDto

/** 지도에 그릴 수 있는 핀. 좌표가 없는 핀(실시간 핀 #382, 아직 위치를 못 찾은 핀)은 목록에는 남고 지도에는 올리지 않는다. */
export type PlacedPin = Pin & { id: string; lat: number; lng: number }
export function isPlaced(pin: Pin): pin is PlacedPin {
  return typeof pin.id === 'string' && typeof pin.lat === 'number' && typeof pin.lng === 'number'
}

export type PinCategory = Pin['category']
/** ♥ 좋음 / 🚫 반대. △ 조율 필요는 2026-10-07에 없앴다(#360). 서버가 아직 neutral 을 줄 수 있는 동안엔 화면에서 걸러 쓴다. */
export type ReactionType = 'like' | 'against'
const isReactionType = (t: string): t is ReactionType => t === 'like' || t === 'against'
/** 서버가 준 반응 종류를 화면 종류로. 없애기로 한 neutral 이 오면 반응이 없는 것으로 본다. */
export const asReactionType = (t: string | undefined): ReactionType | null => (t && isReactionType(t) ? t : null)

/** v1에 핀으로 만들 수 있는 카테고리만 칩으로 둔다 — 숙소·기타는 핀을 만들 수 없다(#191). */
export const FILTER_CATEGORIES: PinCategory[] = ['음식점', '카페', '관광지']

export const SORTS = {
  most: '의견 많은 순',
  least: '의견 적은 순',
  recent: '최근 추가 순',
} as const
export type PinSort = keyof typeof SORTS

/** 의견 필터(기획안 4절). 'none' = 내가 아직 의견을 안 남긴 핀. */
export const OPINIONS = { like: '♥ 좋음', against: '🚫 반대', unknown: '? 미확인', none: '내가 아직 안 남김' } as const
export type PinOpinion = keyof typeof OPINIONS
/** 종류 필터(기획안 5-2: 확정/일반/AI 추천 셋뿐). */
export const KINDS: Pin['kind'][] = ['확정', '일반', 'AI추천']

export type PinFilters = {
  category: PinCategory | null
  createdBy: string | null
  kind: Pin['kind'] | null
  opinion: PinOpinion | null
  sort: PinSort
}

/** ♥·🚫 중 하나라도 남긴 사람 수. 한 사람은 한 핀에 반응 하나만 남긴다. */
export function participants(pin: Pin): number {
  const s = pin.reaction_summary
  return s.like + s.against
}

/**
 * 핀 색의 참여율(docs/design/colors.md 3절). 분모는 지도 전체 구성원 수, 구성원 수만큼 끊는다.
 * 구성원 수를 아직 모르면 0으로 본다 — 0% 핀도 테두리로 또렷하다.
 */
export function participationRatio(pin: Pin, memberCount: number): number {
  if (memberCount <= 0) return 0
  return Math.min(1, participants(pin) / memberCount)
}

/** 이 핀에 이 의견이 있는가. unknown 은 아직 안 남긴 구성원이 있다는 뜻이라 구성원 수가 필요하다. */
function hasOpinion(pin: Pin, opinion: PinOpinion, memberCount: number): boolean {
  switch (opinion) {
    case 'like':
      return pin.reaction_summary.like > 0
    case 'against':
      return pin.reaction_summary.against > 0
    case 'unknown':
      return participants(pin) < memberCount
    case 'none':
      return !pin.my_reaction
  }
}

export function filterPins(pins: Pin[], f: PinFilters, memberCount = 0): Pin[] {
  const kept = pins.filter(
    (p) =>
      (!f.category || p.category === f.category) &&
      (!f.createdBy || p.created_by === f.createdBy) &&
      (!f.kind || p.kind === f.kind) &&
      (!f.opinion || hasOpinion(p, f.opinion, memberCount)),
  )
  if (f.sort === 'recent') return kept.sort(byNewest)
  const dir = f.sort === 'most' ? -1 : 1
  // 같은 참여 수면 원래 순서를 지킨다(Array.prototype.sort 는 안정 정렬).
  return kept.sort((a, b) => dir * (participants(a) - participants(b)))
}

/** 최근에 찍은 핀이 앞으로. created_at 은 ISO 8601 이라 문자열 비교로 시간 순서가 맞지 않을 수 있어(시간대 표기) 숫자로 비교한다. */
export const byNewest = (a: Pin, b: Pin) => Date.parse(b.created_at) - Date.parse(a.created_at)

/** "방금 전" · "10분 전" · "3시간 전" · "2일 전". */
export function timeAgo(iso: string, now = Date.now()): string {
  const min = Math.floor((now - Date.parse(iso)) / 60_000)
  if (min < 1) return '방금 전'
  if (min < 60) return `${min}분 전`
  if (min < 60 * 24) return `${Math.floor(min / 60)}시간 전`
  return `${Math.floor(min / (60 * 24))}일 전`
}

export type PinCardView = {
  id: string
  name: string
  meta: string
  counts: Record<ReactionType | 'unknown', number>
  mine: ReactionType | null
}

/** 카드 한 장. 미확인(?)은 구성원 수에서 반응한 사람을 뺀 값이다. */
/** myId: 내가 찍은 핀은 이름 대신 「내가 찍음」(기획안 9절 — 내 것은 항상 나로 보인다). */
export function toPinCard(pin: Pin, memberCount: number, myId?: string): PinCardView {
  const s = pin.reaction_summary
  return {
    id: pin.id,
    name: pin.place_name ?? '이름 없는 장소',
    meta: [
      pin.category,
      pin.created_by === myId ? '내가 찍음' : pin.created_by_display_name && `${pin.created_by_display_name}님이 찍음`,
      timeAgo(pin.created_at),
    ]
      .filter(Boolean)
      .join(' · '),
    counts: { ...s, unknown: Math.max(0, memberCount - participants(pin)) },
    mine: asReactionType(pin.my_reaction?.type),
  }
}

export type PinCreateRequest = components['schemas']['PinCreateRequest']
export type ReactionDto = components['schemas']['Reaction']
export type ReactionRequest = components['schemas']['ReactionRequest']
/** 반대 사유 칩(최종기획안 5-1-1). 목록은 서버가 카테고리별로 준다 — 화면엔 label, 요청엔 id. */
export type ReasonChip = components['schemas']['ReasonChip']
/** 지도 전체 집계. 쓰는 건 「2/4명이 의견을 남겼어요」(members_with_opinion·members_total)뿐이다. */
export type FilterCounts = components['schemas']['FilterCounts']

/** 내 반응을 바꾼 뒤의 핀. 서버 응답(Reaction)에는 집계가 없어서 직접 고친다 — SSE 가 오면 그 집계로 덮인다. */
export function withMyReaction(pin: Pin, next: ReactionDto | null): Pin {
  const s = { ...pin.reaction_summary }
  const prev = pin.my_reaction?.type
  if (prev) s[prev] = Math.max(0, s[prev] - 1)
  if (next) s[next.type] += 1
  return { ...pin, my_reaction: next, reaction_summary: s }
}

export type OpinionView = { userId: string; name: string; isMe: boolean; type: ReactionType; chips: string[]; text?: string }

/**
 * 핀 상세 「구성원 의견」(Figma 구성원 의견 표시 원칙). 위 집계 줄과 같은 내용을 되풀이하지 않는다 —
 * 갈린 의견(반대)만 카드로 펼치고, 좋음은 한 줄로 접고, 미확인은 이름을 보여준다.
 */
export function toOpinions(
  reactions: ReactionDto[],
  members: { userId: string; name: string; isMe: boolean }[],
  chips: ReasonChip[] = [],
) {
  const labelOf = (id: string) => chips.find((c) => c.id === id)?.label ?? id
  const nameOf = (userId: string) => members.find((m) => m.userId === userId)
  const views: OpinionView[] = reactions.filter((r) => isReactionType(r.type)).map((r) => {
    const m = nameOf(r.user_id)
    return {
      userId: r.user_id,
      name: m?.name ?? r.display_name ?? '구성원',
      isMe: m?.isMe ?? false,
      type: r.type as ReactionType,
      chips: (r.reason_chip_ids ?? []).map(labelOf),
      text: r.reason_text || undefined,
    }
  })
  const reacted = new Set(reactions.map((r) => r.user_id))
  return {
    split: views.filter((v) => v.type === 'against'),
    likes: views.filter((v) => v.type === 'like'),
    unknown: members.filter((m) => !reacted.has(m.userId)),
  }
}
