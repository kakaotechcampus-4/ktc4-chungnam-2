import { fireEvent, render, screen } from '@testing-library/react'
import { createPortal } from 'react-dom'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'

import BottomSheet from './BottomSheet'

beforeAll(() => {
  // 휴대폰 화면 — 단계와 끌기가 있는 시트다.
  vi.stubGlobal('matchMedia', (query: string) => ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }))
  // jsdom 에는 포인터 캡처가 없다.
  Element.prototype.setPointerCapture ??= () => {}
})
afterAll(() => vi.unstubAllGlobals())

/** 시트 안에서 그렸지만 포털로 body 에 붙는 것(알림함 같은 모달 시트). React 이벤트는 React 트리를 따라 시트까지 올라온다. */
const Modal = () => createPortal(<div>모달 안</div>, document.body)

describe('포털로 띄운 모달의 누름은 바텀시트를 움직이지 않는다', () => {
  it('제목 줄의 모달을 눌러도 단계가 바뀌지 않는다(프로필 탭 알림함)', () => {
    const onStageChange = vi.fn()
    render(<BottomSheet stage={2} onStageChange={onStageChange} header={<Modal />}>본문</BottomSheet>)
    fireEvent.pointerDown(screen.getByText('모달 안'), { pointerId: 1, clientY: 100 })
    fireEvent.pointerUp(screen.getByText('모달 안'), { pointerId: 1, clientY: 100 })
    expect(onStageChange).not.toHaveBeenCalled()
  })

  it('2단계 자동 확장 본문의 모달을 밀어도 3단계로 올리지 않는다', () => {
    const onStageChange = vi.fn()
    render(<BottomSheet stage={2} onStageChange={onStageChange} header="머리" expandOnScroll><Modal /></BottomSheet>)
    const inModal = screen.getByText('모달 안')
    fireEvent.touchStart(inModal, { touches: [{ clientY: 300 }] })
    fireEvent.touchMove(inModal, { touches: [{ clientY: 200 }] })
    fireEvent.wheel(inModal, { deltaY: 100 })
    expect(onStageChange).not.toHaveBeenCalled()
  })

  it('시트 자신의 제목 줄을 누르면 여전히 접힌다', () => {
    const onStageChange = vi.fn()
    render(<BottomSheet stage={2} onStageChange={onStageChange} header={<p>머리</p>}>본문</BottomSheet>)
    fireEvent.pointerDown(screen.getByText('머리'), { pointerId: 1, clientY: 100 })
    fireEvent.pointerUp(screen.getByText('머리'), { pointerId: 1, clientY: 100 })
    expect(onStageChange).toHaveBeenCalledWith(1)
  })
})
