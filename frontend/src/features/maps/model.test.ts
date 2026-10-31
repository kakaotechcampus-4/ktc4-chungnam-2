import { describe, expect, it } from 'vitest'

import { mapChanges, toInviteRowView } from './model'

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
