import { describe, expect, it } from 'vitest'

import { filenameFrom } from './api'

describe('filenameFrom (#484 내보내기 파일 이름)', () => {
  it('한글 이름은 filename* 을 풀어서 쓴다', () => {
    expect(filenameFrom(`attachment; filename="shortlist.csv"; filename*=UTF-8''%EC%A0%9C%EC%A3%BC.csv`)).toBe('제주.csv')
  })
  it('filename* 이 없으면 ASCII 이름', () => {
    expect(filenameFrom('attachment; filename="shortlist.txt"')).toBe('shortlist.txt')
  })
  it('헤더가 없으면(다른 오리진이라 가려짐) 없음', () => {
    expect(filenameFrom(null)).toBeUndefined()
  })
})
