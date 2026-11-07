import { describe, expect, it } from 'vitest'

import { randomGuestName } from './guestName'

describe('randomGuestName', () => {
  it('형용사 + 동물 두 낱말이고, 난수 끝값에서도 목록 밖으로 나가지 않는다', () => {
    expect(randomGuestName(() => 0)).toBe('신나는 수달')
    expect(randomGuestName(() => 0.999999)).toBe('상냥한 거북이')
  })
})
