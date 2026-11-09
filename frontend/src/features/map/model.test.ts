import { describe, expect, it } from 'vitest'

import { authorName, FILTER_CATEGORIES, inputExample } from './model'

describe('입력칸 예시 문장(#1461)', () => {
  const KINDS = ['like', 'against', 'memo'] as const

  it('핀으로 만들 수 있는 카테고리마다 좋음·반대·메모 예시가 다르다', () => {
    for (const kind of KINDS) {
      const examples = FILTER_CATEGORIES.map((c) => inputExample(c, kind))
      expect(new Set(examples).size, kind).toBe(FILTER_CATEGORIES.length)
      for (const e of examples) expect(e).toMatch(/^예: /)
    }
  })

  it('숙소·기타·분류 모름은 같은 공통 문장이다', () => {
    for (const kind of KINDS) {
      const common = inputExample(null, kind)
      expect(inputExample(undefined, kind)).toBe(common)
      expect(inputExample('숙소', kind)).toBe(common)
      expect(inputExample('기타', kind)).toBe(common)
      expect(FILTER_CATEGORIES.map((c) => inputExample(c, kind))).not.toContain(common)
    }
  })

  it('음식점 예시가 카페·관광지에 나오지 않는다', () => {
    expect(inputExample('카페', 'like')).not.toContain('국물')
    expect(inputExample('관광지', 'memo')).not.toContain('곱창')
  })
})

describe('authorName — 탈퇴한 작성자', () => {
  it('서버의 「탈퇴한 구성원」과 빈 이름은 「(알 수 없음)」, 나머지는 그대로', () => {
    expect(authorName({ created_by_display_name: '탈퇴한 구성원' })).toBe('(알 수 없음)')
    expect(authorName({ created_by_display_name: null })).toBe('(알 수 없음)')
    expect(authorName({ created_by_display_name: '나간 구성원' })).toBe('나간 구성원')
    expect(authorName({ created_by_display_name: '민수' })).toBe('민수')
  })
})
