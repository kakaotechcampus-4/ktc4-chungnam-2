import { describe, expect, it } from 'vitest'

import html from '../../../index.html?raw'

import { FEATURES } from './features'

/** index.html 의 정적 소개(#1614)는 JS를 돌리지 않는 크롤러가 읽는다. 기능 문장이 화면과 어긋나면 여기서 걸린다. */
describe('index.html 정적 소개', () => {
  it.each(FEATURES.map((f) => f.text))('%s', (text) => {
    expect(html).toContain(`<li>${text}</li>`)
  })

  it('기능 줄 수가 같다', () => {
    expect(html.match(/<li>/g)).toHaveLength(FEATURES.length)
  })
})
