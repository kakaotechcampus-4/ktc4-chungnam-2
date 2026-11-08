import { render, screen } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'


import { wholeText } from '@/test/text'

import RegionPicker from './RegionPicker'

beforeAll(() => {
  // jsdom 에는 matchMedia 가 없다(시트 닫힘 효과가 동작 줄이기를 본다).
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterAll(() => vi.unstubAllGlobals())

describe('지도 만들기 지역 고르기', () => {
  it('고를 수 있는 곳만 짧은 이름 칸으로, 베타는 아래 문장, 준비 중인 곳은 보이지 않는다', () => {
    render(<RegionPicker value={null} onDone={() => {}} onClose={() => {}} />)
    const cell = (name: string) => screen.getByRole('button', { name })

    // 데이터를 주력으로 모은 서울·대전은 베타가 아니다.
    expect(cell('서울특별시')).toHaveTextContent(/^서울$/)
    expect(cell('대전광역시')).toHaveTextContent(/^대전$/)
    for (const name of ['부산광역시 베타', '대구광역시 베타', '광주광역시 베타']) expect(cell(name)).toBeEnabled()
    expect(cell('강원특별자치도 춘천만 베타')).toHaveTextContent('강원(춘천)')
    expect(screen.getByText(wholeText('부산 · 대구 · 광주 · 강원은 베타예요. 장소 정보가 아직 적을 수 있어요'))).toBeInTheDocument()

    // 준비 중인 곳은 보이지 않는다.
    expect(screen.queryByText(/제주|준비 중/)).not.toBeInTheDocument()
  })

  it('고르면 정식 이름으로 정한다', async () => {
    const onDone = vi.fn()
    render(<RegionPicker value={null} onDone={onDone} onClose={() => {}} />)
    screen.getByRole('button', { name: '대전광역시' }).click()
    ;(await screen.findByRole('button', { name: '대전광역시로 정하기' })).click()
    expect(onDone).toHaveBeenCalledWith(expect.objectContaining({ label: '대전광역시' }))
  })
})
