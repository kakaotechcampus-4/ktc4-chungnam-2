import { describe, expect, it } from 'vitest'

import { josaRo } from './josa'

describe('josaRo', () => {
  it('받침이 있으면 「으로」, 없거나 ㄹ 받침이면 「로」', () => {
    expect(josaRo('장현성')).toBe('으로')
    expect(josaRo('민재')).toBe('로')
    expect(josaRo('한별')).toBe('로')
    expect(josaRo('Tom')).toBe('로')
  })
})
