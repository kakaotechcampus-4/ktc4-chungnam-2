import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import PeopleProof from './PeopleProof'

describe('PeopleProof', () => {
  it('남긴 사람 얼굴을 넷까지 겹치고 넘치면 +N, 숫자는 글로 적는다', () => {
    const { container } = render(<PeopleProof names={['민재', '준영', '강준', '관호', '도윤']} total={6} verb="이 의견을 남겼어요" />)
    expect(screen.getByText('5명').parentElement).toHaveTextContent('6명 중 5명이 의견을 남겼어요')
    expect(container.querySelectorAll('.rounded-full.ring-2')).toHaveLength(5) // 얼굴 4 + 「+1」
    expect(screen.getByText('+1')).toBeInTheDocument()
  })
  it('아무도 없으면 얼굴 없이 글만', () => {
    render(<PeopleProof names={[]} total={4} verb="이 의견을 남겼어요" />)
    expect(screen.getByText('0명').parentElement).toHaveTextContent('4명 중 0명이 의견을 남겼어요')
  })
})
