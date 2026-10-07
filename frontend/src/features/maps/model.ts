import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'

export type MapDto = components['schemas']['Map']
export type MapCreateRequest = components['schemas']['MapCreateRequest']
export type MemberDto = components['schemas']['Member']
export type InviteDto = components['schemas']['Invite']
export type InviteSummaryDto = components['schemas']['InviteSummary']
export type MapRegion = components['schemas']['MapRegion']

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

/** 초대 수락 실패 문구. 코드와 문구는 docs/errors.md 표를 따른다. */
const INVITE_ERROR_MESSAGES: Record<string, string> = {
  INVITE_NOT_FOUND: '유효하지 않은 초대 링크예요',
  INVITE_EXPIRED: '초대 링크가 만료됐어요. 초대한 분께 새 링크를 요청하세요',
  MAP_LIMIT: '지도는 10개까지 만들거나 참여할 수 있어요. 다른 지도를 나가거나 삭제한 뒤 다시 시도해 주세요',
}

/** 지도 만들기 실패 문구. 10개를 넘으면 409 MAP_LIMIT(#369). */
export function createMapErrorMessage(err: unknown): string {
  return err instanceof ApiError && err.code === 'MAP_LIMIT' ? INVITE_ERROR_MESSAGES.MAP_LIMIT : '지도를 만들지 못했어요'
}

export function inviteErrorMessage(err: unknown): string {
  return (err instanceof ApiError && INVITE_ERROR_MESSAGES[err.code]) || '참여하지 못했어요'
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
