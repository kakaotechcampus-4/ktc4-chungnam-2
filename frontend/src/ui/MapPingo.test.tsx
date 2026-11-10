import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import type { MapHeading } from '@/features/shell/sheetStore'

import MapPingo from './MapPingo'

/** 처음 보이는 그림의 파일 이름. 그림 파일 이름은 핑고가 보는 쪽이다(#1746). */
const shown = (heading: MapHeading | null) => {
  const { container, unmount } = render(<MapPingo heading={heading} />)
  const src = container.querySelector('img')?.getAttribute('src') ?? ''
  unmount()
  return src.split('/').pop()?.replace(/\.png.*$/, '')
}

describe('지도 위 핑고 — heading 쪽을 보는 그림(#1746)', () => {
  it('8방향 모두 그쪽을 보는 그림을 고른다', () => {
    expect(shown('left')).toBe('walk-left-1')
    expect(shown('right')).toBe('walk-right-1')
    expect(shown('up')).toBe('back')
    expect(shown('down')).toBe('front')
    expect(shown('up-left')).toBe('diag-up-left')
    expect(shown('up-right')).toBe('diag-up-right')
    expect(shown('down-left')).toBe('diag-down-left')
    expect(shown('down-right')).toBe('diag-down-right')
  })

  it('서 있으면 정면이다', () => {
    expect(shown(null)).toBe('front')
  })
})
