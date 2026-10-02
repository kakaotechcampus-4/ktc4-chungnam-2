import type { components } from '@pingo/contracts/src/types/api'

import { ApiError } from '@/api'

export type MapDto = components['schemas']['Map']
export type MapCreateRequest = components['schemas']['MapCreateRequest']
export type MemberDto = components['schemas']['Member']
export type InviteDto = components['schemas']['Invite']

export type MapView = Pick<MapDto, 'id' | 'title'> & {
  /** 목록 한 줄 요약 — "2026-10-03 ~ 2026-10-05 · 3명" */
  summary: string
}

/** "10.3 (토) ~ 10.5 (월)" — 프로필 모달 머리글(Figma 8절). */
export function formatTripDates(start: string, end: string): string {
  const fmt = (iso: string) => {
    const d = new Date(`${iso}T00:00:00`)
    return `${d.getMonth() + 1}.${d.getDate()} (${'일월화수목금토'[d.getDay()]})`
  }
  return start === end ? fmt(start) : `${fmt(start)} ~ ${fmt(end)}`
}

export type MapHeaderView = Pick<MapDto, 'id' | 'title'> & { dates: string; memberCount: number }

export function toMapHeaderView(map: MapDto): MapHeaderView {
  return {
    id: map.id,
    title: map.title,
    dates: formatTripDates(map.start_date, map.end_date),
    memberCount: map.member_count,
  }
}

export type MemberView = { userId: string; name: string; initial: string; isMe: boolean }

export function toMemberView(member: MemberDto, myUserId: string | undefined): MemberView {
  const name = member.display_name ?? '이름 없음'
  return { userId: member.user_id, name, initial: name.slice(0, 1), isMe: member.user_id === myUserId }
}

export function toMapView(map: MapDto): MapView {
  return {
    id: map.id,
    title: map.title,
    summary: `${map.start_date} ~ ${map.end_date} · ${map.member_count}명`,
  }
}

/** 초대 수락 실패 문구. 코드와 문구는 docs/errors.md 표를 따른다. */
const INVITE_ERROR_MESSAGES: Record<string, string> = {
  INVITE_NOT_FOUND: '유효하지 않은 초대 링크예요',
  INVITE_EXPIRED: '초대 링크가 만료됐어요. 초대한 분께 새 링크를 요청하세요',
}

export function inviteErrorMessage(err: unknown): string {
  return (err instanceof ApiError && INVITE_ERROR_MESSAGES[err.code]) || '참여하지 못했어요'
}
