import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import MapAppLinks from './MapAppLinks'

it('핀 상세 줄: 카카오맵·네이버 지도 버튼을 새 창 링크로 두고, 연 것을 알린다', () => {
  const onOpen = vi.fn()
  render(<MapAppLinks kakao="https://place.map.kakao.com/1" naver="https://map.naver.com/p/search/a" onOpen={onOpen} />)
  const kakao = screen.getByRole('link', { name: '카카오맵에서 보기, 새 창' })
  expect(kakao).toHaveAttribute('href', 'https://place.map.kakao.com/1')
  expect(kakao).toHaveAttribute('target', '_blank')
  expect(kakao).toHaveAttribute('rel', 'noopener noreferrer')
  expect(screen.getByRole('link', { name: '네이버 지도에서 보기, 새 창' })).toHaveAttribute('href', 'https://map.naver.com/p/search/a')
  kakao.click()
  expect(onOpen).toHaveBeenCalledTimes(1)
})

it('링크가 없는 서비스는 그리지 않고, 둘 다 없으면 아무것도 그리지 않는다', () => {
  const { container, rerender } = render(<MapAppLinks kakao={null} naver="https://map.naver.com/p/search/a" />)
  expect(screen.queryByRole('link', { name: /카카오맵/ })).toBeNull()
  expect(screen.getByRole('link', { name: /네이버 지도/ })).toBeInTheDocument()
  rerender(<MapAppLinks kakao={null} naver={undefined} />)
  expect(container).toBeEmptyDOMElement()
})
