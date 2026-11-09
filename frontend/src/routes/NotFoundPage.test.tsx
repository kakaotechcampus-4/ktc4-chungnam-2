import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { expect, it } from 'vitest'

import NotFoundPage from './NotFoundPage'

/** 없는 주소는 구글이 색인하지 않아야 한다(#1677). React가 <title>, <meta>를 <head>로 올리는지까지 본다. */
it('없는 주소 화면은 제목과 noindex를 head에 둔다', async () => {
  render(
    <MemoryRouter>
      <NotFoundPage />
    </MemoryRouter>,
  )
  expect(screen.getByRole('link', { name: '처음 화면으로' })).toHaveAttribute('href', '/')
  expect(document.title).toBe('페이지를 찾을 수 없어요 | 핑고핑고')
  expect(document.head.querySelector('meta[name="robots"]')).toHaveAttribute('content', 'noindex')
})
