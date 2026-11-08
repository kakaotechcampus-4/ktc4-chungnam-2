import { describe, expect, it } from 'vitest'

import type { Pin, ReactionDto } from './model'
import { diffSince, snapshotOf, type Seen } from './newSince'

const ME = 'me'
const pin = (id: string, like: number, against: number, extra: Partial<Pin> = {}): Pin =>
  ({
    id,
    map_id: 'm',
    category: '음식점',
    kind: '일반',
    visibility: 'public',
    created_by: 'u1',
    created_at: '2026-11-05T10:00:00Z',
    reaction_summary: { like, against },
    permissions: {},
    ...extra,
  }) as Pin
const r = (pinId: string, userId: string, type: 'like' | 'against', reason_text?: string): ReactionDto => ({ pin_id: pinId, user_id: userId, type, reason_text })

const seen: Seen = { at: '2026-11-05T12:00:00Z', pins: { a: { like: 1, against: 0 }, b: { like: 0, against: 1, who: { u2: 'against' } } } }

describe('diffSince', () => {
  it('지난번 뒤에 남이 찍은 핀만 새 핀이다 — 내 핀, 되살린 옛 핀은 빼고', () => {
    const pins = [
      pin('a', 1, 0),
      pin('new', 0, 0, { created_at: '2026-11-05T20:00:00Z' }),
      pin('mine', 0, 0, { created_at: '2026-11-05T20:00:00Z', created_by: ME }),
      pin('restored', 0, 0, { created_at: '2026-11-01T00:00:00Z' }),
    ]
    const news = diffSince(seen, pins, ME, () => undefined)
    expect([...news.keys()]).toEqual(['new'])
    expect(news.get('new')?.newPin).toBe(true)
  })

  it('누가 남겼는지 알던 핀은 달라진 사람만 새 의견이다(♥에서 반대로 바꾼 것도)', () => {
    const pins = [pin('b', 0, 3)]
    const news = diffSince(seen, pins, ME, () => [r('b', 'u2', 'against'), r('b', 'u3', 'against', '비싸요'), r('b', ME, 'against')])
    expect(news.get('b')?.opinions.map((o) => o.user_id)).toEqual(['u3'])
  })

  it('처음 보는 핀: 그 반응이 전부 새로 생겼으면 다 새것, 일부만 늘었으면 수만 보인다', () => {
    const all = diffSince(seen, [pin('a', 1, 1)], ME, () => [r('a', 'u1', 'like'), r('a', 'u4', 'against')])
    expect(all.get('a')?.opinions.map((o) => o.user_id)).toEqual(['u4'])
    const some = diffSince(seen, [pin('a', 2, 0)], ME, () => [r('a', 'u1', 'like'), r('a', 'u4', 'like')])
    expect(some.get('a')).toEqual({ newPin: false, opinions: [], counted: { like: 1 } })
  })

  it('의견 목록을 아직 못 받았으면 늘어난 수만, 줄기만 했으면 소식이 없다', () => {
    expect(diffSince(seen, [pin('a', 3, 0)], ME, () => undefined).get('a')?.counted).toEqual({ like: 2 })
    expect(diffSince(seen, [pin('a', 0, 0)], ME, () => undefined).size).toBe(0)
  })
})

describe('snapshotOf', () => {
  it('의견 수를 적고, 받아 둔 의견 목록이 있으면 누가 무엇을 남겼는지도 적는다', () => {
    const s = snapshotOf([pin('a', 1, 0), pin('b', 0, 0)], (id) => (id === 'a' ? [r('a', 'u1', 'like')] : undefined), new Date('2026-11-06T00:00:00Z'))
    expect(s).toEqual({ at: '2026-11-06T00:00:00.000Z', pins: { a: { like: 1, against: 0, who: { u1: 'like' } }, b: { like: 0, against: 0 } } })
  })
})
