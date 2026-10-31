import { describe, expect, it } from 'vitest'

import { isLinkInput } from './model'

describe('isLinkInput (#487 검색창에 붙인 링크)', () => {
  it('http(s) 링크면 링크로 본다 — 구글·카카오인지는 서버가 정한다', () => {
    expect(isLinkInput('https://maps.app.goo.gl/abc')).toBe(true)
    expect(isLinkInput('http://place.map.kakao.com/123')).toBe(true)
    expect(isLinkInput('https://blog.naver.com/x')).toBe(true)
  })
  it('이름이나 링크가 섞인 글은 이름 검색이다', () => {
    expect(isLinkInput('성수 곱창')).toBe(false)
    expect(isLinkInput('여기 https://kko.to/a 가자')).toBe(false)
  })
})
