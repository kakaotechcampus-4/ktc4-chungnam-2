import { fireEvent, render, screen } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

import BottomSheet from './BottomSheet'
import type { SheetStage } from './sheetStore'

beforeAll(() => {
  // 휴대폰 화면 — 단계가 있는 시트.
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} }))
})
afterAll(() => vi.unstubAllGlobals())

function renderSheet(stage: SheetStage) {
  const onStageChange = vi.fn()
  render(
    <BottomSheet stage={stage} onStageChange={onStageChange} header={<p>머리</p>} expandOnScroll>
      <div data-sheet-expand>
        <button type="button">반대</button>
      </div>
      <button type="button">확정 리스트에 넣기</button>
    </BottomSheet>,
  )
  return onStageChange
}

describe('시트 2단계에서 누르면 펼쳐지는 자리(#1694)', () => {
  it('data-sheet-expand 안을 누르면 누름이 끝난 뒤 3단계로 편다', () => {
    const onStageChange = renderSheet(2)
    fireEvent.click(screen.getByRole('button', { name: '반대' }))
    expect(onStageChange).toHaveBeenCalledWith(3)
  })

  it('그 밖의 버튼은 눌러도 펴지 않는다(누르는 동안 시트가 움직여 빗나가지 않게, #1675)', () => {
    const onStageChange = renderSheet(2)
    fireEvent.click(screen.getByRole('button', { name: '확정 리스트에 넣기' }))
    expect(onStageChange).not.toHaveBeenCalled()
  })

  it('이미 3단계면 그대로 둔다', () => {
    const onStageChange = renderSheet(3)
    fireEvent.click(screen.getByRole('button', { name: '반대' }))
    expect(onStageChange).not.toHaveBeenCalled()
  })
})
