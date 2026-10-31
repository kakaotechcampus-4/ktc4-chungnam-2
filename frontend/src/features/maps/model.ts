import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'

export type MapDto = components['schemas']['Map']
export type MapListDto = components['schemas']['MapList']
export type MapCreateRequest = components['schemas']['MapCreateRequest']
export type MemberDto = components['schemas']['Member']
export type InviteDto = components['schemas']['Invite']
export type InviteSummaryDto = components['schemas']['InviteSummary']
export type MapRegion = components['schemas']['MapRegion']
export type TrashedMapListDto = components['schemas']['TrashedMapList']

export type MapView = Pick<MapDto, 'id' | 'title'> & {
  /** 지역 태그. 지도를 만들 때 고르지 않았으면 없다. */
  region?: string
  /** 내가 만든 지도인가. 서버가 아직 안 채우면 없다 — 그땐 목록을 나누지 않는다. */
  createdByMe?: boolean
  /** 지금 내가 방장인가(위임되면 바뀐다). */
  isOwner: boolean
  /** 목록 한 줄 요약 — "10.3 (토) ~ 10.5 (월) · 구성원 4명 · 핀 3개" */
  summary: string
}

/** "10.3 (토) ~ 10.5 (월)" — 프로필 모달 머리글(Figma 8절). */
export function formatTripDates(start: string, end: string): string {
  const fmt = (iso: string) => {
    const d = new Date(`${iso}T00:00:00`)
    return `${d.getMonth() + 1}.${d.getDate()} (${'일월화수목금토'[d.getDay()]})`
  }
  return start === end ? `${fmt(start)} 당일치기` : `${fmt(start)} ~ ${fmt(end)}`
}

export type MapHeaderView = Pick<MapDto, 'id' | 'title'> & {
  dates: string
  memberCount: number
  /** 지도 삭제는 방장만(#369). */
  canDelete: boolean
  /** 넘길 사람이 없는 방장은 나갈 수 없다 — 지도를 삭제해야 한다. */
  canLeave: boolean
  /** 방장이 나가면 방장이 될 사람의 이름. 요청자가 방장이고 넘길 사람이 있을 때만 있다. */
  nextOwnerName?: string
  /** 지도를 만들 때 고른 지역의 가운데. 실시간 핀의 위치를 이 근처에서 찾는다(#382). 고르지 않았으면 없다. */
  regionCenter?: { lat: number; lng: number }
}

export function toMapHeaderView(map: MapDto): MapHeaderView {
  return {
    id: map.id,
    title: map.title,
    dates: formatTripDates(map.start_date, map.end_date),
    memberCount: map.member_count,
    regionCenter: map.region ? { lat: map.region.lat, lng: map.region.lng } : undefined,
    canDelete: map.permissions.can_delete === true,
    canLeave: map.permissions.can_leave !== false,
    nextOwnerName: map.next_owner?.display_name,
  }
}

export type MemberView = { userId: string; name: string; initial: string; isMe: boolean; isOwner: boolean }

export function toMemberView(member: MemberDto, myUserId: string | undefined): MemberView {
  const name = member.display_name ?? '이름 없음'
  return { userId: member.user_id, name, initial: name.slice(0, 1), isMe: member.user_id === myUserId, isOwner: member.role === 'owner' }
}

export function toMapView(map: MapDto): MapView {
  return {
    id: map.id,
    title: map.title,
    region: map.region?.label,
    createdByMe: map.created_by_me,
    isOwner: map.my_role === 'owner',
    summary: `${formatTripDates(map.start_date, map.end_date)} · 구성원 ${map.member_count}명 · 핀 ${map.pin_count}개`,
  }
}

/** 내 지도 목록과 상한(#623). 상한은 서버가 내려 준 값만 쓴다. */
export type MapListView = {
  items: MapView[]
  limit: number
  /** 상한까지 찼다 — 「새 지도」를 막는다. */
  full: boolean
}

export function toMapListView(list: MapListDto): MapListView {
  return { items: list.items.map(toMapView), limit: list.limit, full: list.items.length >= list.limit }
}

/** 상한이라 「새 지도 만들기」를 막았을 때 곁에 두는 안내(지도 목록, PC 지도 바꾸기 메뉴). */
export const MAP_LIMIT_HINT = '다른 지도를 나가거나 삭제하면 다시 만들 수 있어요'

/** 휴지통(#464, #479). 기간(retentionDays)과 남은 날수(daysLeft)는 서버가 센다 — 화면은 날짜를 계산하지 않는다. */
export type TrashView = {
  retentionDays: number
  items: { id: string; title: string; dates: string; daysLeft: number }[]
}

export function toTrashView(list: TrashedMapListDto): TrashView {
  return {
    retentionDays: list.retention_days,
    items: list.items.map((m) => ({ id: m.id, title: m.title, dates: formatTripDates(m.start_date, m.end_date), daysLeft: m.days_left })),
  }
}

/** 지도 삭제 확인 창의 안내. 기간을 아직 못 받았으면 숫자 없이 쓴다(상한 숫자처럼 화면이 들고 있지 않는다). */
export function deleteMapBody(title: string, retentionDays?: number): string {
  const when = retentionDays ? `${retentionDays}일 안에는` : '정해진 기간 안에는'
  return `‘${title}’의 핀과 의견이 모든 구성원에게서 사라져요. ${when} 내 지도 목록의 휴지통에서 복구할 수 있어요.`
}

/**
 * 복구 실패 문구. 복구도 지도를 하나 늘리는 일이라 상한(409 MAP_LIMIT)에 걸릴 수 있다.
 * MAP_PURGED 문구는 docs/errors.md 그대로이고, 날수만 휴지통 응답의 retention_days로 채운다.
 */
export function restoreMapErrorMessage(err: unknown, retentionDays: number): string {
  if (err instanceof ApiError && err.code === 'MAP_LIMIT') return mapLimitMessage(err)
  if (err instanceof ApiError && err.code === 'MAP_PURGED') return `삭제한 지 ${retentionDays}일이 지나 복구할 수 없어요`
  return '지도를 복구하지 못했어요'
}

/** 초대 수락 실패 문구. 코드와 문구는 docs/errors.md 표를 따른다. */
const INVITE_ERROR_MESSAGES: Record<string, string> = {
  INVITE_NOT_FOUND: '유효하지 않은 초대 링크예요',
  INVITE_EXPIRED: '초대 링크가 만료됐어요. 초대한 분께 새 링크를 요청하세요',
}

/** 상한 숫자는 화면이 들고 있지 않는다 — 409 MAP_LIMIT 응답의 detail.limit만 쓴다(멘토 리뷰 #380). */
function mapLimitMessage(err: ApiError): string {
  const limit = typeof err.detail?.limit === 'number' ? `${err.detail.limit}개까지` : '정해진 개수까지'
  return `지도는 ${limit} 만들거나 참여할 수 있어요. 다른 지도를 나가거나 삭제한 뒤 다시 시도해 주세요`
}

/** 지도 만들기 실패 문구. 상한을 넘으면 409 MAP_LIMIT(#369). */
export function createMapErrorMessage(err: unknown): string {
  return err instanceof ApiError && err.code === 'MAP_LIMIT' ? mapLimitMessage(err) : '지도를 만들지 못했어요'
}

export function inviteErrorMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return '참여하지 못했어요'
  if (err.code === 'MAP_LIMIT') return mapLimitMessage(err)
  return INVITE_ERROR_MESSAGES[err.code] ?? '참여하지 못했어요'
}

export type InviteView = { title: string; dates: string; memberCount: number; pinCount: number; inviter: string }

export function toInviteView(invite: InviteSummaryDto): InviteView {
  return {
    title: invite.title,
    dates: formatTripDates(invite.start_date, invite.end_date),
    memberCount: invite.member_count,
    pinCount: invite.pin_count,
    inviter: invite.inviter_display_name,
  }
}

/** 초대 요약을 못 받은 이유. 만료·없는 링크는 화면을 따로 띄운다(Figma C-3). */
export function inviteProblem(err: unknown): 'expired' | 'invalid' | null {
  if (!(err instanceof ApiError)) return null
  if (err.code === 'INVITE_EXPIRED') return 'expired'
  if (err.code === 'INVITE_NOT_FOUND') return 'invalid'
  return null
}
