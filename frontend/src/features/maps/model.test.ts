import { describe, expect, it } from 'vitest'

import { toInviteRowView } from './model'

describe('toInviteRowView (#481 켜진 초대 링크 한 줄)', () => {
  it('만든 사람·참여 수·만료일을 한 줄로', () => {
    const row = toInviteRowView({ token: 't1', url: 'u', expires_at: '2026-11-07T12:00:00+09:00', created_by_display_name: '민수', used_count: 2 })
    expect(row).toEqual({ token: 't1', label: '민수님이 만든 링크 · 2명 참여 · 11.7 (토)까지' })
  })
  it('목록 밖 응답처럼 칸이 비면 0명으로', () => {
    expect(toInviteRowView({ token: 't2', url: 'u', expires_at: '2026-11-07T12:00:00+09:00' }).label).toBe('초대 링크 · 0명 참여 · 11.7 (토)까지')
  })
})
