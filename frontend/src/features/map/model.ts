import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'
import { UNKNOWN_NAME } from '@/ui/UnknownName'

export type PinDto = components['schemas']['Pin']
/** 핀 상세 블로그 사진 한 장(#1157) — 카카오 미리보기 주소, 원문 글 주소, 출처 사이트 이름. */
export type PinPhotoDto = components['schemas']['PinPhoto']
/** 지금은 응답 그대로다. 화면용으로 바꿀 게 생기면(반응 집계 등) 여기서 바꾸고 화면은 그대로 둔다. */
export type Pin = PinDto

/** 지도에 그릴 수 있는 핀. 좌표가 없는 핀(실시간 핀 #382, 아직 위치를 못 찾은 핀)은 목록에는 남고 지도에는 올리지 않는다. */
export type PlacedPin = Pin & { id: string; lat: number; lng: number }
export function isPlaced(pin: Pin): pin is PlacedPin {
  return typeof pin.id === 'string' && typeof pin.lat === 'number' && typeof pin.lng === 'number'
}

export type PinCategory = Pin['category']

/**
 * AI 추천에서 지도에 올린 핀인지. 서버는 올릴 때 근거(이유·조건 체크·구성원 충족·출처)를 핀에 그대로 옮기고(가드레일 5),
 * 확정되면 kind 는 「확정」이 되지만 근거는 남는다 — 그래서 kind 가 아니라 근거가 있는지로 본다(#1032).
 */
/** 서버는 작성자가 탈퇴했으면 이름 자리에 '탈퇴한 구성원'을 내린다(api-spec Pin.created_by_display_name). 화면은 이름을 모른다고만 보인다. */
const WITHDRAWN_NAME = '탈퇴한 구성원'
export const authorName = (pin: { created_by_display_name?: string | null }) =>
  !pin.created_by_display_name || pin.created_by_display_name === WITHDRAWN_NAME ? UNKNOWN_NAME : pin.created_by_display_name
export const hasAiEvidence = (pin: Pin) => Boolean(pin.reason || pin.checks?.length)
/** ♥ 좋음 / 🚫 반대. △ 조율 필요는 2026-10-07에 없앴다(#360). 서버가 아직 neutral 을 줄 수 있는 동안엔 화면에서 걸러 쓴다. */
export type ReactionType = 'like' | 'against'
const isReactionType = (t: string): t is ReactionType => t === 'like' || t === 'against'
/** 서버가 준 반응 종류를 화면 종류로. 없애기로 한 neutral 이 오면 반응이 없는 것으로 본다. */
export const asReactionType = (t: string | undefined): ReactionType | null => (t && isReactionType(t) ? t : null)

/** v1에 핀으로 만들 수 있는 카테고리만 칩으로 둔다 — 숙소·기타는 핀을 만들 수 없다(#191). */
export const FILTER_CATEGORIES: PinCategory[] = ['음식점', '카페', '관광지']

type ExampleKind = ReactionType | 'memo'

/**
 * 의견·메모 입력칸의 예시 문장(#1461). 카테고리마다 다르다 — 「국물」「곱창」 예시가 카페·관광지 핀에서 어색했다.
 * 반대 예시는 그 카테고리의 사유 칩(docs/constraints.md 칩 표)에 없는 이유로 골라, 칩에 없는 이유를 글로 쓰게 한다.
 * 알러지 같은 안전 조건은 예시로 쓰지 않는다(가드레일 8).
 */
const INPUT_EXAMPLES: Record<'음식점' | '카페' | '관광지' | 'other', Record<ExampleKind, string>> = {
  음식점: { like: '예: 국물이 진하고 양이 많아요', against: '예: 메뉴가 적어서 고를 게 없어요', memo: '예: 여기 곱창 맛있대' },
  카페: { like: '예: 창가 자리가 넓고 조용해요', against: '예: 콘센트가 없어서 오래 있기 힘들어요', memo: '예: 여기 디저트가 유명하대' },
  관광지: { like: '예: 야경이 예뻐서 사진 찍기 좋아요', against: '예: 볼거리가 적어서 금방 지루해요', memo: '예: 해 질 녘에 가면 예쁘대' },
  other: { like: '예: 위치가 좋아서 들르기 편해요', against: '예: 지난번 여행 때 가봤어요', memo: '예: 친구가 꼭 가 보래' },
}

/** 입력칸 예시 문장. 숙소·기타나 분류를 모르면 공통 문장이다. */
export function inputExample(category: PinCategory | null | undefined, kind: ExampleKind): string {
  const key = category === '음식점' || category === '카페' || category === '관광지' ? category : 'other'
  return INPUT_EXAMPLES[key][kind]
}

export const SORTS = {
  most: '의견 많은 순',
  least: '의견 적은 순',
  recent: '최근 추가 순',
} as const
export type PinSort = keyof typeof SORTS

/** 의견 필터(기획안 4절). 'none' = 내가 아직 의견을 안 남긴 핀. */
// 필터 드롭다운(<option>)용 글자 — <option> 안에는 아이콘을 넣을 수 없고, 🚫 이모지는 OS마다 모양이 달라 기호를 뺀다.
export const OPINIONS = { like: '좋음', against: '반대', unknown: '미확인', none: '내가 아직 안 남김' } as const
export type PinOpinion = keyof typeof OPINIONS
/** 종류 필터(기획안 5-2: 확정/일반/AI 추천 셋뿐). */
export const KINDS: Pin['kind'][] = ['확정', '일반', 'AI추천']
/** 핀 종류를 화면·읽는 이름에 적을 때. 값 「AI추천」은 띄어 쓴다(용어 「AI 추천」, 기획안 9절). */
export const kindLabel = (kind: Pin['kind']) => (kind === 'AI추천' ? 'AI 추천' : kind)

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

/** 할 일 핀 — 확정되지 않았고 내 의견이 없다. 확정 핀은 의견을 안 남겨도 할 일로 보지 않는다(#859). 목록 묶음과 "내가 남긴 의견" 카드가 같이 쓴다(#1696). */
export const isTodo = (pin: Pin) => pin.kind !== '확정' && !pin.my_reaction

export type PinCardView = {
  id: string
  name: string
  category: PinCategory
  meta: string
  counts: Record<ReactionType | 'unknown', number>
  mine: ReactionType | null
  /** 확정 리스트에 든 핀. 카드에선 「의견 남기기」보다 먼저 보인다(#859). */
  confirmed: boolean
}

/** 카드 한 장. 미확인(?)은 구성원 수에서 반응한 사람을 뺀 값이다. */
/** myId: 내가 찍은 핀은 이름 대신 「내가 찍음」(기획안 9절 — 내 것은 항상 나로 보인다). */
export function toPinCard(pin: Pin, memberCount: number, myId?: string): PinCardView {
  const s = pin.reaction_summary
  return {
    id: pin.id,
    name: pin.place_name ?? '이름 없는 장소',
    category: pin.category,
    meta: [
      pin.category,
      pin.created_by === myId ? '내가 찍음' : `${authorName(pin)}님이 찍음`,
      timeAgo(pin.created_at),
    ]
      .filter(Boolean)
      .join(' · '),
    counts: { ...s, unknown: Math.max(0, memberCount - participants(pin)) },
    mine: asReactionType(pin.my_reaction?.type),
    confirmed: pin.kind === '확정',
  }
}

export type PinCreateRequest = components['schemas']['PinCreateRequest']
/** 실시간 핀 승격의 매칭 힌트(#501). 서버도 화면도 저장하지 않는다. */
export type PinResolveRequest = components['schemas']['PinResolveRequest']
export type PinUpdateRequest = components['schemas']['PinUpdateRequest']

/**
 * 핀 수정 실패 문구(#466). 무엇이 안 되는지(의견이 달린 핀의 분류 등)는 서버가 정하고 문구까지 내려 준다 —
 * 화면이 같은 규칙을 다시 판정하지 않고 422 문구를 그대로 쓴다(멘토 리뷰 #680).
 */
export function pinEditErrorMessage(err: unknown): string {
  return err instanceof ApiError && err.code === 'VALIDATION_ERROR' ? err.message : '핀을 고치지 못했어요'
}

/** 핀 휴지통(#864). 보관 일수는 응답의 retention_days 로 적는다 — 화면에 숫자를 따로 두지 않는다. */
export type PinTrash = components['schemas']['PinTrash']
export type TrashedPin = components['schemas']['TrashedPin']

/** 되살리기 실패 문구. 휴지통에 있는 동안 같은 장소로 새 핀이 생겼으면 409 PIN_DUPLICATE 다(api-spec /pins/{pinId}/restore). */
export function restorePinErrorMessage(err: unknown): string {
  return err instanceof ApiError && err.code === 'PIN_DUPLICATE' ? '이미 지도에 같은 장소가 있어요' : '핀을 되돌리지 못했어요'
}

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
