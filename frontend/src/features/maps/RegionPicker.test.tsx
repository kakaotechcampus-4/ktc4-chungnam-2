import { render, screen } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

import RegionPicker from './RegionPicker'

beforeAll(() => {
  // jsdom 에는 matchMedia 가 없다(시트 닫힘 효과가 동작 줄이기를 본다).
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterAll(() => vi.unstubAllGlobals())

describe('지도 만들기 지역 고르기', () => {
  it('데이터를 주력으로 모은 서울·대전은 그대로, 나머지 열린 곳은 (베타)와 아래 안내, 닫힌 곳은 준비 중', () => {
    render(<RegionPicker value={null} onDone={() => {}} onClose={() => {}} />)
    const chip = (name: string) => screen.getByRole('button', { name: new RegExp(`^${name}`) })

    for (const name of ['서울특별시', '대전광역시']) {
      expect(chip(name)).toBeEnabled()
      expect(chip(name)).not.toHaveTextContent('베타')
    }
    for (const name of ['부산광역시', '대구광역시', '광주광역시']) {
      expect(chip(name)).toBeEnabled()
      expect(chip(name)).toHaveTextContent(`${name}(베타)`)
    }
    expect(chip('강원특별자치도')).toHaveTextContent('강원특별자치도· 춘천만(베타)')
    expect(chip('제주특별자치도')).toBeDisabled()
    expect(chip('제주특별자치도')).toHaveTextContent('준비 중')
    expect(screen.getByText('(베타) 지역은 장소 정보가 아직 적을 수 있어요')).toBeInTheDocument()
  })
})
