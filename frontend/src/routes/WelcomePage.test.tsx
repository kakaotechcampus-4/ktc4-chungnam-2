import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { FEATURES } from '@/features/onboarding/features'
import { hasSeenWelcome } from '@/features/onboarding/welcomeSeen'

import WelcomePage from './WelcomePage'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
})

function setup() {
  render(
    <MemoryRouter initialEntries={['/welcome']}>
      <Routes>
        <Route path="/welcome" element={<WelcomePage />} />
        <Route path="/" element={<p>내 지도</p>} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('첫 로그인 온보딩', () => {
  it('기능마다 한 장씩 넘기고, 마지막 장의 「시작하기」로 본 것을 남기고 목록으로 간다', async () => {
    setup()
    expect(hasSeenWelcome()).toBe(false)
    for (const { text } of FEATURES.slice(0, -1)) {
      expect(screen.getByRole('heading', { name: text })).toBeInTheDocument()
      await userEvent.click(screen.getByRole('button', { name: '다음' }))
    }
    expect(screen.getByRole('heading', { name: FEATURES.at(-1)!.text })).toBeInTheDocument()
    // 마지막 장엔 건너뛸 게 없다.
    expect(screen.queryByRole('button', { name: '건너뛰기' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '시작하기' }))
    expect(screen.getByText('내 지도')).toBeInTheDocument()
    expect(hasSeenWelcome()).toBe(true)
  })

  it('「건너뛰기」도 본 것으로 남긴다', async () => {
    setup()
    await userEvent.click(screen.getByRole('button', { name: '건너뛰기' }))
    expect(screen.getByText('내 지도')).toBeInTheDocument()
    expect(hasSeenWelcome()).toBe(true)
  })

  it('저장소가 막힌 브라우저에선 본 것으로 친다 — 목록에 올 때마다 다시 뜨지 않게', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    expect(hasSeenWelcome()).toBe(true)
  })
})
