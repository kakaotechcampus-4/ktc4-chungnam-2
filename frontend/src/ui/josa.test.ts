import { describe, expect, it } from 'vitest'

import { josa } from './josa'

describe('josa', () => {
  it('한글 끝 글자의 받침으로 고른다', () => {
    expect(josa('대천 여행', '을', '를')).toBe('을')
    expect(josa('카페', '을', '를')).toBe('를')
  })
  it('숫자는 읽는 소리로 본다', () => {
    expect(josa('카페 1', '을', '를')).toBe('을') // 일
    expect(josa('카페 2', '을', '를')).toBe('를') // 이
    expect(josa('3', '이', '가')).toBe('이') // 삼
  })
  it('끝의 괄호·따옴표·공백은 건너뛴다', () => {
    expect(josa('식당(본관)', '을', '를')).toBe('을')
    expect(josa('「핑고」 ', '을', '를')).toBe('를')
  })
  it('한글이 아니거나 비어 있으면 받침 없는 쪽', () => {
    expect(josa('Cafe', '을', '를')).toBe('를')
    expect(josa('', '을', '를')).toBe('를')
  })
})
