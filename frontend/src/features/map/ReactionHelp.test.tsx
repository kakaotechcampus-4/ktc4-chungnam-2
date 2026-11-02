import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import ReactionHelp from './ReactionHelp'

describe('좋음·반대·미확인 설명(#1030)', () => {
  it('누르면 미확인이 아직 의견을 남기지 않은 사람 수라는 것과 반대·확정 리스트가 무엇에 쓰이는지 보인다', async () => {
    render(<ReactionHelp />)
    await userEvent.click(screen.getByRole('button', { name: '좋음·반대·미확인이 무엇인지 보기' }))

    expect(await screen.findByText('아직 의견을 남기지 않은 사람 수예요')).toBeInTheDocument()
    expect(screen.getByText('가기 어려운 곳이에요. 남긴 이유로 AI가 다른 곳을 찾아요')).toBeInTheDocument()
    expect(screen.getByText('가기로 정한 곳이에요. 「확정된 장소」 탭에서 들를 순서를 봐요')).toBeInTheDocument()
  })
})
