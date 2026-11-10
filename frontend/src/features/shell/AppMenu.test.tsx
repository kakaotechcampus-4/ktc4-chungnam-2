import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'

import AppMenu from './AppMenu'

function renderMenu() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/maps/map_1']}>
        <Routes>
          <Route path="/maps/:mapId" element={<AppMenu mapId="map_1" />} />
          <Route path="/" element={<h1>내 지도 목록</h1>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('☰ 메뉴(#1538)', () => {
  it('「내 지도 목록」는 내 지도 목록으로 간다', async () => {
    renderMenu()
    await userEvent.click(screen.getByRole('button', { name: '메뉴' }))
    await userEvent.click(screen.getByRole('button', { name: '내 지도 목록' }))
    expect(screen.getByRole('heading', { name: '내 지도 목록' })).toBeInTheDocument()
  })

  it('「버그 신고하기」는 메뉴를 닫고 버그를 골라 둔 의견 창을 연다(창 제목이 분류를 따른다)', async () => {
    renderMenu()
    await userEvent.click(screen.getByRole('button', { name: '메뉴' }))
    await userEvent.click(screen.getByRole('button', { name: '버그 신고하기' }))
    expect(screen.queryByRole('button', { name: '내 지도 목록' })).not.toBeInTheDocument()
    expect(screen.getByRole('dialog', { name: '버그 신고하기' })).toBeInTheDocument()
  })

  it('「설정」을 펼치면 약관과 회원 탈퇴가 보이고, 자주 묻는 질문은 답을 펼쳐 본다', async () => {
    renderMenu()
    await userEvent.click(screen.getByRole('button', { name: '메뉴' }))
    expect(screen.queryByRole('link', { name: '핑고핑고 이용약관' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '설정' }))
    expect(screen.getByRole('link', { name: '핑고핑고 이용약관' })).toHaveAttribute('href', '/terms')
    expect(screen.getByRole('button', { name: '회원 탈퇴' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: '자주 묻는 질문' }))
    const question = screen.getByRole('button', { name: '친구는 어떻게 초대하나요?' })
    expect(question).toHaveAttribute('aria-expanded', 'false')
    await userEvent.click(question)
    expect(question).toHaveAttribute('aria-expanded', 'true')
  })
})
