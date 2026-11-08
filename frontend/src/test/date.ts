import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

/** `DatePicker` 칸을 열고 'YYYY-MM-DD' 날을 고른다. 달력은 고른 날(없으면 오늘)의 달로 열려서 그 달까지 넘긴다. */
export async function pickDate(label: string | RegExp, day: string) {
  await userEvent.click(screen.getByLabelText(label, { selector: 'button[aria-haspopup]' }))
  const calendar = await screen.findByRole('dialog', { name: '날짜 고르기' })
  const [y, m, d] = day.split('-').map(Number)
  const [shownY, shownM] = (within(calendar).getByText(/^\d+년 \d+월$/).textContent ?? '').match(/\d+/g)!.map(Number)
  const months = y * 12 + m - (shownY * 12 + shownM)
  for (let i = 0; i < Math.abs(months); i++) {
    await userEvent.click(within(calendar).getByRole('button', { name: months < 0 ? '이전 달' : '다음 달' }))
  }
  await userEvent.click(within(calendar).getByRole('button', { name: new RegExp(`^${y}년 ${m}월 ${d}일 `) }))
}
