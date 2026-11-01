import { describe, expect, it } from 'vitest'

import { ApiError } from '@/api'

import { feedbackErrorMessage } from './model'

describe('feedbackErrorMessage (#10)', () => {
  it('상한이면 잠시 뒤 다시, 숫자는 적지 않는다', () => {
    const msg = feedbackErrorMessage(new ApiError(429, { code: 'RATE_LIMITED', message: '요청이 너무 잦습니다' }))
    expect(msg).toContain('잠시 뒤')
    expect(msg).not.toMatch(/\d/)
  })
  it('그 밖은 일반 문구', () => {
    expect(feedbackErrorMessage(new Error('x'))).toBe('의견을 보내지 못했어요')
  })
})
