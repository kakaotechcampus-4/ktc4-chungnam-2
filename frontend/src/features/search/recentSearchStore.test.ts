import { describe, expect, it } from 'vitest'

import { pushRecent, RECENT_MAX } from './recentSearchStore'

describe('pushRecent', () => {
  it('맨 앞에 넣고, 같은 검색어는 앞으로 올리고, 상한만큼만 남긴다', () => {
    expect(pushRecent(['국밥', '카페'], '카페')).toEqual(['카페', '국밥'])
    const many = Array.from({ length: RECENT_MAX }, (_, i) => `q${i}`)
    const next = pushRecent(many, '새 검색')
    expect(next).toHaveLength(RECENT_MAX)
    expect(next[0]).toBe('새 검색')
    expect(next).not.toContain(`q${RECENT_MAX - 1}`)
  })
})
