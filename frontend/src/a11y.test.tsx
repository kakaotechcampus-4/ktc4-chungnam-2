import { act, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import Toaster from '@/features/shell/Toaster'
import { showToast, useToastStore } from '@/features/shell/toast'
import SheetTitle from '@/ui/SheetTitle'

// #959 핵심 흐름 접근성 — 시트 제목 포커스, 알림 영역, 토스트 멈춤.

function Swap() {
  const [detail, setDetail] = useState(false)
  return detail ? <SheetTitle>핀 상세</SheetTitle> : <button onClick={() => setDetail(true)}>열기</button>
}

describe('#959', () => {
  afterEach(() => {
    vi.useRealTimers()
    useToastStore.setState({ toast: null })
  })

  it('누른 버튼이 사라지면 새 시트 제목으로 포커스가 간다', () => {
    render(<Swap />)
    const button = screen.getByRole('button', { name: '열기' })
    button.focus()
    fireEvent.click(button)
    expect(screen.getByRole('heading', { name: '핀 상세' })).toHaveFocus()
  })

  it('포커스가 남아 있으면 시트 제목이 뺏지 않는다', () => {
    render(
      <>
        <input aria-label="검색" autoFocus />
        <SheetTitle>마킹된 장소</SheetTitle>
      </>,
    )
    expect(screen.getByRole('textbox', { name: '검색' })).toHaveFocus()
  })

  it('토스트가 없어도 알림 영역은 늘 있다', () => {
    render(<Toaster controlsVisible={false} />)
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
    act(() => showToast('핀을 찍었어요'))
    expect(screen.getByRole('status')).toHaveTextContent('핀을 찍었어요')
  })

  it('포커스가 토스트 안에 있는 동안은 사라지지 않고, 떠나면 다시 센다', () => {
    vi.useFakeTimers()
    render(
      <>
        <button>밖</button>
        <Toaster controlsVisible={false} />
      </>,
    )
    act(() => showToast('의견을 거뒀어요', { label: '되돌리기', onClick: () => {} }))
    act(() => screen.getByRole('button', { name: '되돌리기' }).focus())
    act(() => vi.advanceTimersByTime(10_000))
    expect(screen.getByRole('status')).toHaveTextContent('의견을 거뒀어요')

    act(() => screen.getByRole('button', { name: '밖' }).focus())
    act(() => vi.advanceTimersByTime(10_000))
    expect(screen.getByRole('status')).toBeEmptyDOMElement()
  })
})
