import { onlineManager } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import { afterEach, expect, it } from 'vitest'

import BusyLabel from './BusyLabel'
import CardSkeleton from './CardSkeleton'
import PingoLoading from './PingoLoading'
import Skeleton from './Skeleton'

const offline = () => act(() => onlineManager.setOnline(false))
afterEach(() => act(() => onlineManager.setOnline(true)))

const TITLE = '인터넷 연결이 끊겼어요'

it('끊기면 기다림 부품이 끝없이 도는 대신 안내로 바뀌고(#1722), 돌아오면 원래대로다', () => {
  render(<CardSkeleton label="목록" />)
  expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
  offline()
  expect(screen.getByText(TITLE)).toBeInTheDocument()
  expect(screen.getByText('연결되면 자동으로 이어서 불러와요')).toBeInTheDocument()
  act(() => onlineManager.setOnline(true))
  expect(screen.queryByText(TITLE)).not.toBeInTheDocument()
})

it('걷는 핑고도 안내로 바뀐다', () => {
  offline()
  render(<PingoLoading label="불러오는 중" />)
  expect(screen.getByText(TITLE)).toBeInTheDocument()
})

it('작은 스켈레톤은 한 줄이다', () => {
  offline()
  render(<Skeleton label="칩">뼈대</Skeleton>)
  expect(screen.getByRole('status')).toHaveTextContent(TITLE)
  expect(screen.queryByText('연결되면 자동으로 이어서 불러와요')).not.toBeInTheDocument()
})

it('버튼은 기다리는 중일 때만 "연결되면 보낼게요"다', () => {
  offline()
  const { rerender } = render(<BusyLabel busy={false} busyText="저장하는 중…">저장</BusyLabel>)
  expect(screen.getByText('저장')).toBeInTheDocument()
  rerender(<BusyLabel busy busyText="저장하는 중…">저장</BusyLabel>)
  expect(screen.getByText('연결되면 보낼게요')).toBeInTheDocument()
})
