import { describe, expect, it } from 'vitest'

import type { MapNewsDto } from './api'
import type { Pin } from './model'
import { newsLines, toPinNews } from './newSince'

const pin = (id: string): Pin => ({ id, category: '음식점', reaction_summary: { like: 0, against: 0 } }) as Pin
const r = (pinId: string, userId: string, type: 'like' | 'against', reason_text?: string) => ({
  pin_id: pinId,
  user_id: userId,
  display_name: userId,
  type,
  reason_chip_ids: [],
  updated_at: '2026-11-10T00:00:00Z',
  ...(reason_text ? { reason_text } : {}),
})
const news = (extra: Partial<MapNewsDto>): MapNewsDto => ({ since: '2026-11-09T00:00:00Z', new_pin_ids: [], new_reactions: [], truncated: false, ...extra })

describe('toPinNews — 서버가 준 새 소식을 핀마다 묶는다(#1556)', () => {
  it('새 핀과 새 의견을 같은 핀에 모으고, 그새 지워진 핀은 뺀다', () => {
    const byPin = toPinNews(news({ new_pin_ids: ['a', 'gone'], new_reactions: [r('a', 'u2', 'like'), r('b', 'u3', 'against'), r('gone', 'u2', 'like')] }), [pin('a'), pin('b')])
    expect([...byPin.keys()]).toEqual(['a', 'b'])
    expect(byPin.get('a')).toEqual({ newPin: true, opinions: [r('a', 'u2', 'like')] })
    expect(byPin.get('b')?.newPin).toBe(false)
  })
})

describe('newsLines', () => {
  it('사유는 글이 있으면 글이고, 두 줄을 넘으면 외 N개로 접는다', () => {
    const lines = newsLines({ newPin: false, opinions: [r('a', '김도현', 'against', '비싸요'), r('a', '박서영', 'like'), r('a', '이유빈', 'like')] }, (x) => x.user_id, () => undefined)
    expect(lines).toEqual(['김도현님 반대 · 비싸요', '외 2개'])
  })
})
