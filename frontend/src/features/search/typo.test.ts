import { describe, expect, it } from 'vitest'

import { suggestQuery } from './typo'

describe('검색어 오타 제안', () => {
  it('자모 하나 틀린 음식 종류를 고친다', () => {
    expect(suggestQuery('중곡집')).toBe('중국집')
    expect(suggestQuery('감자당')).toBe('감자탕')
    expect(suggestQuery('삼겹쌀')).toBe('삼겹살')
  })

  it('받침이 빠진 것도 고친다', () => {
    expect(suggestQuery('중국지')).toBe('중국집')
  })

  it('지역 이름은 두고 틀린 낱말만 고친다', () => {
    expect(suggestQuery('성수 중곡집')).toBe('성수 중국집')
  })

  it('맞는 말, 사전에 없는 이름, 한 글자, 영어는 고치지 않는다', () => {
    expect(suggestQuery('중국집')).toBeNull()
    expect(suggestQuery('중곡')).toBeNull()
    expect(suggestQuery('소문난성수감자탕')).toBeNull()
    expect(suggestQuery('국')).toBeNull()
    expect(suggestQuery('starbucks')).toBeNull()
  })
})
