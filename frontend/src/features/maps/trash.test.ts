import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { deleteMapBody, restoreMapErrorMessage } from './model'

describe('휴지통 문구 (#479) — 기간과 상한은 서버 값만 쓴다', () => {
  it('삭제 안내의 기간은 서버의 retention_days', () => {
    expect(deleteMapBody('제주', 7)).toContain('7일 안에는')
    expect(deleteMapBody('제주')).not.toMatch(/\d+일/)
  })
  it('복구 상한은 detail.limit, 기간이 지나면 숫자 없이', () => {
    const limit = new ApiError(409, { code: 'MAP_LIMIT', message: '', detail: { limit: 20, count: 20 } })
    expect(restoreMapErrorMessage(limit)).toContain('20개까지')
    expect(restoreMapErrorMessage(new ApiError(410, { code: 'MAP_PURGED', message: '' }))).toBe('되살릴 수 있는 기간이 지났어요')
  })
})
