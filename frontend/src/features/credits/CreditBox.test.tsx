import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import CreditBox from './CreditBox'

describe('CreditBox', () => {
  it('쓸 크레딧과 남은 크레딧을 글로 보이고, 누르면 크레딧 설명이 뜬다', async () => {
    render(<CreditBox cost={1} credits={{ balance: 29, max_balance: 30 }} />)
    expect(screen.getByText('1 크레딧 사용')).toBeInTheDocument()
    expect(screen.getByText('남은 크레딧 29/30')).toBeInTheDocument()
    expect(screen.queryByText('크레딧은 무엇인가요?')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: /크레딧 설명 보기/ }))
    expect(await screen.findByText('크레딧은 무엇인가요?')).toBeInTheDocument()
  })

  it('크레딧을 쓰지 않는 실행은 「크레딧 안 써요」', () => {
    render(<CreditBox cost={0} credits={{ balance: 29, max_balance: 30 }} />)
    expect(screen.getByText('크레딧 안 써요')).toBeInTheDocument()
  })
})
