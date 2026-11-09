import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { Pin } from '@/features/map/model'
import { wholeText } from '@/test/text'

import { MyOpinionProgress } from './MapTab'

const pin = (id: string, kind: Pin['kind'], mine: boolean) =>
  ({ id, kind, place_name: `장소${id}`, my_reaction: mine ? { type: 'like' } : undefined }) as unknown as Pin

describe('내 의견 카드(#1547)', () => {
  it('확정되지 않은 핀 중 내가 남긴 수와 %, 끝낸 곳 하나와 남은 곳 — 남은 곳을 누르면 그 핀이 열린다', async () => {
    const onOpen = vi.fn()
    render(
      <MyOpinionProgress
        pins={[pin('a', '일반', true), pin('b', '일반', false), pin('c', 'AI추천', false), pin('d', '확정', false)]}
        onOpen={onOpen}
        onShowLeft={() => {}}
      />,
    )
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '3곳 중 1곳')
    expect(screen.getByText('33%')).toBeInTheDocument()
    expect(screen.getAllByRole('listitem').map((li) => li.textContent)).toEqual(['끝난 일: 장소a', '장소b', '장소c'])
    expect(screen.getByText(wholeText('남은 2곳에 의견을 남기면 AI 추천이 더 정확해져요'))).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '남은 일: 장소b' }))
    expect(onOpen).toHaveBeenCalledWith('b')
    // 줄에 다 보이면 「모두 보기」는 없다.
    expect(screen.queryByRole('button', { name: /모두 보기/ })).not.toBeInTheDocument()
  })

  it('남은 곳이 줄보다 많으면 「남은 N곳 모두 보기」가 남은 핀 필터를 연다', async () => {
    const onShowLeft = vi.fn()
    render(<MyOpinionProgress pins={['a', 'b', 'c', 'd'].map((id) => pin(id, '일반', false))} onOpen={() => {}} onShowLeft={onShowLeft} />)
    await userEvent.click(screen.getByRole('button', { name: '남은 4곳 모두 보기' }))
    expect(onShowLeft).toHaveBeenCalled()
  })

  it('다 남겼으면(확정 핀은 빼고) 그리지 않는다', () => {
    const { container } = render(<MyOpinionProgress pins={[pin('a', '일반', true), pin('d', '확정', false)]} onOpen={() => {}} onShowLeft={() => {}} />)
    expect(container).toBeEmptyDOMElement()
  })
})
