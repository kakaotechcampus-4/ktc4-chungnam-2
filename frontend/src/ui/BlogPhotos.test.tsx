import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import BlogPhotos from './BlogPhotos'

const PHOTOS = [
  { thumbnail_url: 'data:image/svg+xml,a', link_url: 'https://blog.naver.com/a/1', site_name: '네이버블로그' },
  { thumbnail_url: 'data:image/svg+xml,b', link_url: 'https://blog.naver.com/a/2', site_name: '네이버블로그' },
  { thumbnail_url: 'data:image/svg+xml,c', link_url: 'https://brunch.co.kr/a/3', site_name: '' },
]

it('블로그 사진이라고 밝히고, 사진마다 출처와 새 창을 읽어 주는 원문 링크다', () => {
  render(<BlogPhotos photos={PHOTOS} />)
  expect(screen.getByRole('region', { name: '블로그 사진' })).toBeInTheDocument()
  const first = screen.getByRole('link', { name: '블로그 사진 1, 네이버블로그, 새 창' })
  expect(first).toHaveAttribute('href', 'https://blog.naver.com/a/1')
  expect(first).toHaveAttribute('target', '_blank')
  expect(first).toHaveAttribute('rel', 'noopener noreferrer')
  // 출처 이름을 모르면 "출처"로 읽는다
  expect(screen.getByRole('link', { name: '블로그 사진 3, 출처, 새 창' })).toBeInTheDocument()
  // 보이는 출처 줄은 이름이 있는 것만, 같은 이름은 한 번
  expect(screen.getByText('네이버블로그')).toBeInTheDocument()
})

it('불러오는 동안은 빈 칸, 실패와 없음은 같은 높이의 빈 칸과 짧은 글이다(화면이 밀리지 않게)', () => {
  const { container, rerender } = render(<BlogPhotos loading />)
  expect(screen.queryByRole('link')).toBeNull()
  expect(container.querySelectorAll('.animate-pulse')).toHaveLength(3)
  rerender(<BlogPhotos failed />)
  expect(screen.getByText('사진을 불러오지 못했어요')).toBeInTheDocument()
  rerender(<BlogPhotos photos={[]} />)
  expect(screen.getByText('블로그 사진을 찾지 못했어요')).toBeInTheDocument()
  expect(screen.queryByRole('link')).toBeNull()
  // 세 상태 모두 72px 칸(size-18)을 가진다
  for (const state of [{ loading: true }, { failed: true }, { photos: [] }]) {
    rerender(<BlogPhotos {...state} />)
    expect(container.querySelector('.size-18')).not.toBeNull()
  }
})
