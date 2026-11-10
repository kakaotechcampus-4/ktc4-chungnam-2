import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { describe, expect, it } from 'vitest'

import type { Pin } from '@/features/map/model'
import { wholeText } from '@/test/text'

import { MyOpinionProgress } from './MapTab'

const pin = (id: string, kind: Pin['kind'], mine: boolean) =>
  ({ id, kind, place_name: `장소${id}`, my_reaction: mine ? { type: 'like' } : undefined }) as unknown as Pin

describe('내 의견 카드(#1547)', () => {
  it('확정되지 않은 핀 중 내가 남긴 수와 %를 보이고, 핀 이름 줄은 두지 않는다(#1733)', () => {
    render(<MyOpinionProgress pins={[pin('a', '일반', true), pin('b', '일반', false), pin('c', 'AI추천', false), pin('d', '확정', false)]} />)
    expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuetext', '3곳 중 1곳')
    expect(screen.getByText('33%')).toBeInTheDocument()
    expect(screen.getByText(wholeText('남은 2곳에 의견을 남기면 AI 추천이 더 정확해져요'))).toBeInTheDocument()
    expect(screen.queryByRole('list')).not.toBeInTheDocument()
    expect(screen.queryByText(/장소/)).not.toBeInTheDocument()
  })

  it('다 남겼으면(확정 핀은 빼고) 완료 카드와 AI 추천 가는 길, 주소가 없으면 그리지 않는다', () => {
    const done = [pin('a', '일반', true), pin('d', '확정', false)]
    const { container, unmount } = render(<MyOpinionProgress pins={done} />)
    expect(container).toBeEmptyDOMElement()
    unmount()
    render(
      <MemoryRouter>
        <MyOpinionProgress pins={done} recommendHref="/maps/m/recommend" />
      </MemoryRouter>,
    )
    expect(screen.getByRole('status')).toHaveTextContent('모든 핀에 의견을 남겼어요')
    expect(screen.getByRole('link', { name: 'AI 추천 받기' })).toHaveAttribute('href', '/maps/m/recommend')
  })
})
