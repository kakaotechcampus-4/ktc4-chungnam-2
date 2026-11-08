import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Pin } from '@/features/map/model'
import { wholeText } from '@/test/text'

import { MyOpinionProgress } from './MapTab'

const pin = (id: string, kind: Pin['kind'], mine: boolean) =>
  ({ id, kind, my_reaction: mine ? { type: 'like' } : undefined }) as unknown as Pin

describe('내 의견 진행 막대(#1547)', () => {
  it('확정되지 않은 핀 중 내가 남긴 수와 남은 곳 — 「남은 곳 보기」는 남은 핀 필터로', async () => {
    const onShowLeft = vi.fn()
    render(<MyOpinionProgress pins={[pin('a', '일반', true), pin('b', '일반', false), pin('c', 'AI추천', false), pin('d', '확정', false)]} onShowLeft={onShowLeft} />)
    expect(screen.getByRole('progressbar', { name: '내 의견' })).toHaveAttribute('aria-valuetext', '3곳 중 1곳')
    expect(screen.getByText(wholeText('남은 2곳에 의견을 남기면 AI 추천이 더 정확해져요'))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '남은 곳 보기' }))
    expect(onShowLeft).toHaveBeenCalled()
  })

  it('다 남겼으면(확정 핀은 빼고) 그리지 않는다', () => {
    const { container } = render(<MyOpinionProgress pins={[pin('a', '일반', true), pin('d', '확정', false)]} onShowLeft={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
