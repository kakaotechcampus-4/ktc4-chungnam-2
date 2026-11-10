import { act, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ConnectionBanner } from './TabSheet'

afterEach(() => vi.useRealTimers())

describe('연결 끊김 띠(#1575)', () => {
  it('자동으로 다시 붙는 중이면 2.5초 지나도 끊겨 있을 때만 띄운다', () => {
    vi.useFakeTimers()
    render(<ConnectionBanner state="reconnecting" onReconnect={() => {}} />)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    act(() => vi.advanceTimersByTime(2500))
    expect(screen.getByRole('status')).toHaveTextContent('연결이 끊겼어요. 다시 연결하는 중…')
  })

  it('다시 붙기를 포기했으면 바로 「다시 연결」과 함께', () => {
    const onReconnect = vi.fn()
    render(<ConnectionBanner state="closed" onReconnect={onReconnect} />)
    screen.getByRole('button', { name: '다시 연결' }).click()
    expect(onReconnect).toHaveBeenCalled()
  })
})
