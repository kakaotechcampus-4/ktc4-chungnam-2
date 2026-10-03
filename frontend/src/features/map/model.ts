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
/** myId: 내가 찍은 핀은 이름 대신 「내가 찍음」(기획안 9절 — 내 것은 항상 나로 보인다). */
export function toPinCard(pin: Pin, memberCount: number, myId?: string): PinCardView {
  const s = pin.reaction_summary
  return {
    id: pin.id,
    name: pin.place_name ?? '이름 없는 장소',
    meta: [pin.category, pin.created_by === myId ? '내가 찍음' : pin.created_by_display_name && `${pin.created_by_display_name}님이 찍음`].filter(Boolean).join(' · '),
    counts: { ...s, unknown: Math.max(0, memberCount - participants(pin)) },
    mine: pin.my_reaction?.type ?? null,
  }
}

export type PinCreateRequest = components['schemas']['PinCreateRequest']
export type ReactionDto = components['schemas']['Reaction']
export type ReactionRequest = components['schemas']['ReactionRequest']

/** 반대 사유 칩(최종기획안 5-1-1). 지금은 음식점만 정해져 있다 — 다른 카테고리는 자유서술만 받는다. */
export const REASON_CHIPS: Partial<Record<PinCategory, string[]>> = {
  음식점: ['매워요', '비싸요', '멀어요', '웨이팅', '가봤어요'],
}
// ponytail: 칩 id 목록이 스펙에 없어 칩 이름을 id로 보낸다(백엔드는 사유 글이 없으면 id를 이어 붙여 사유로 쓴다). id가 정해지면 표로.

/**
 * 내 반응을 바꾼 뒤의 핀(낙관적 반영). 서버 응답(Reaction)에는 집계가 없어서 직접 고친다 —
 * 그래야 같은 변경이 SSE 로 돌아왔을 때 "남이 남긴 의견"으로 오인해 토스트를 띄우지 않는다.
 */
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
 * 갈린 의견(반대 → 조율)만 카드로 펼치고, 좋음은 한 줄로 접고, 미확인은 이름을 보여준다.
 */
export function toOpinions(reactions: ReactionDto[], members: { userId: string; name: string; isMe: boolean }[]) {
  const nameOf = (userId: string) => members.find((m) => m.userId === userId)
  const views: OpinionView[] = reactions.map((r) => {
    const m = nameOf(r.user_id)
    return {
      userId: r.user_id,
      name: m?.name ?? r.display_name ?? '구성원',
      isMe: m?.isMe ?? false,
      type: r.type,
      chips: r.reason_chip_ids ?? [],
      // 칩만 고른 반대는 서버가 칩을 이어 붙여 사유 글로 돌려줄 수 있다 — 같은 말을 두 번 보이지 않는다.
      text: r.reason_text && r.reason_text !== (r.reason_chip_ids ?? []).join(', ') ? r.reason_text : undefined,
    }
  })
  const reacted = new Set(reactions.map((r) => r.user_id))
  return {
    split: [...views.filter((v) => v.type === 'against'), ...views.filter((v) => v.type === 'neutral')],
    likes: views.filter((v) => v.type === 'like'),
    unknown: members.filter((m) => !reacted.has(m.userId)),
  }
}
