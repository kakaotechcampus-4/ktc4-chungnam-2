import { describe, expect, it } from 'vitest'

import { mapChanges } from './model'

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
