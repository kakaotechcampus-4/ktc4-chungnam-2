import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { inviteProblem, mapChanges, toInviteRowView, tripDateError, tripEndMax, tripReady, tripTooLongError } from './model'

const before = { title: '부산 1박 2일', startDate: '2026-11-01', endDate: '2026-11-02', region: { label: '부산', lat: 35.1, lng: 129.0 } }
const draft = { ...before, region: before.region as typeof before.region | null }

describe('mapChanges (#480 지도 수정은 바뀐 칸만)', () => {
  it('바뀐 게 없으면 null — 저장 버튼이 꺼진다', () => {
    expect(mapChanges(before, { ...draft, title: ' 부산 1박 2일 ' })).toBeNull()
  })
  it('바뀐 칸만 보낸다', () => {
    expect(mapChanges(before, { ...draft, title: '부산 2박', endDate: '2026-11-03' })).toEqual({ title: '부산 2박', end_date: '2026-11-03' })
  })
  it('지역은 지우지 않는다 — 비워도 보내지 않는다', () => {
    expect(mapChanges(before, { ...draft, region: null })).toBeNull()
  })
})

describe('toInviteRowView (#481 켜진 초대 링크 한 줄)', () => {
  it('만든 사람·참여 수·만료일을 한 줄로', () => {
    const row = toInviteRowView({ token: 't1', url: 'u', expires_at: '2026-11-07T12:00:00+09:00', created_by_display_name: '민수', used_count: 2 })
    expect(row).toEqual({ token: 't1', label: '민수님이 만든 링크 · 2명 참여 · 11.7 (토)까지' })
  })
  it('목록 밖 응답처럼 칸이 비면 0명으로', () => {
    expect(toInviteRowView({ token: 't2', url: 'u', expires_at: '2026-11-07T12:00:00+09:00' }).label).toBe('초대 링크 · 0명 참여 · 11.7 (토)까지')
  })
})

describe('inviteProblem (#719 더 쓸 수 없는 초대 링크)', () => {
  const err = (status: number, code: string) => new ApiError(status, { code, message: code })
  it('만료·꺼짐·없는 링크는 끝 화면, 그 밖의 실패는 아니다', () => {
    expect([err(410, 'INVITE_EXPIRED'), err(410, 'INVITE_REVOKED'), err(404, 'INVITE_NOT_FOUND')].map(inviteProblem)).toEqual(['expired', 'revoked', 'invalid'])
    expect([err(409, 'GUEST_LIMIT'), err(409, 'MAP_LIMIT'), new Error('x')].map(inviteProblem)).toEqual([null, null, null])
  })
})

describe('여행 기간 상한(#1371) — 상한 일수는 서버 값', () => {
  // 상한 값은 임의다 — 화면이 받은 값으로 막는지만 본다(정책 값은 서버, docs/errors.md TRIP_TOO_LONG).
  const trip = (startDate: string, endDate: string) => ({ title: '여행', region: null, startDate, endDate })

  it('종료일 칸의 끝은 시작일부터 상한 일째(시작일·종료일 포함)', () => {
    expect(tripEndMax('2026-11-01', 3)).toBe('2026-11-03')
    expect(tripEndMax('2026-12-30', 5)).toBe('2027-01-03')
  })

  it('상한을 넘으면 서버 문구, 같으면 통과, 상한을 모르면 막지 않는다', () => {
    expect(tripDateError(trip('2026-11-01', '2026-11-04'), 3)).toBe('여행 기간은 최대 3일까지 정할 수 있어요')
    expect(tripDateError(trip('2026-11-01', '2026-11-03'), 3)).toBeNull()
    expect(tripDateError(trip('2026-11-01', '2027-11-03'))).toBeNull()
    expect(tripDateError(trip('2026-11-02', '2026-11-01'), 3)).toBe('종료일은 시작일과 같거나 뒤여야 해요')
    expect(tripReady(trip('2026-11-01', '2026-11-04'), 3)).toBe(false)
  })

  it('서버가 막으면(422 TRIP_TOO_LONG) detail.limit 으로 같은 문구', () => {
    expect(tripTooLongError(new ApiError(422, { code: 'TRIP_TOO_LONG', message: '', detail: { limit: 7 } }))).toBe('여행 기간은 최대 7일까지 정할 수 있어요')
    expect(tripTooLongError(new ApiError(409, { code: 'MAP_LIMIT', message: '' }))).toBeNull()
  })
})
