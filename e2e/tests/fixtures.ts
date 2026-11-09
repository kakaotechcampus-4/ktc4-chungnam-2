// 로그인한 방장과 구성원 화면, 그리고 화면에서 자주 하는 동작(#1281). 선택자는 역할과 글자로 잡는다 — 화면 코드를 고치지 않는다.
import { test as base, expect, type Browser, type Page } from '@playwright/test'

import { API_URL } from '../playwright.config'

type User = { user_id: string; name: string; session: string }

type Role = 'owner' | 'member' | 'planner' | 'broke'

const users = (): Record<Role, User> => JSON.parse(process.env.E2E_USERS ?? '{}')

async function signedIn(browser: Browser, user: User, use: (page: Page) => Promise<void>) {
  // 카카오 로그인 대신 백엔드가 서명한 세션 쿠키(e2e/seed.py)를 넣는다. 화면(4173)과 API(8010)는 같은 localhost라 쿠키를 함께 쓴다.
  const context = await browser.newContext({ locale: 'ko-KR', viewport: { width: 412, height: 839 }, isMobile: true, hasTouch: true })
  await context.addCookies([{ name: 'session', value: user.session, domain: 'localhost', path: '/' }])
  const page = await context.newPage()
  await use(page)
  await context.close()
}

// planner와 broke는 크레딧 잔액을 보는 시나리오용이다(#1424). 잔액은 사람마다라 다른 시나리오와 사용자를 나눠 쓰지 않는다.
export const test = base.extend<Record<Role, Page>>({
  owner: async ({ browser }, use) => signedIn(browser, users().owner, use),
  member: async ({ browser }, use) => signedIn(browser, users().member, use),
  planner: async ({ browser }, use) => signedIn(browser, users().planner, use),
  broke: async ({ browser }, use) => signedIn(browser, users().broke, use),
})

export { expect }

function isoDate(daysFromToday: number): string {
  const d = new Date()
  d.setDate(d.getDate() + daysFromToday)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

/** 날짜 칸(`ui/DatePicker`)을 열어 그날을 누른다. 고를 날은 오늘 뒤라 달력은 「다음 달」로만 넘긴다. */
async function pickDate(page: Page, label: string, day: string) {
  await page.locator('label', { hasText: label }).locator('button[aria-haspopup]').click()
  const calendar = page.getByRole('dialog', { name: '날짜 고르기' })
  const [y, m, d] = day.split('-').map(Number)
  const button = calendar.getByRole('button', { name: new RegExp(`^${y}년 ${m}월 ${d}일 `) })
  for (let i = 0; i < 12 && !(await button.isVisible()); i++) await calendar.getByRole('button', { name: '다음 달' }).click()
  await button.click()
}

export function mapIdOf(page: Page): string {
  return new URL(page.url()).pathname.split('/')[2]
}

/** 새 지도를 만들고 첫 안내를 닫는다. 여행은 한 달 뒤 1박 2일이다(지난 여행이면 관찰과 영업 판정이 달라진다). */
export async function createMap(page: Page, title: string) {
  await page.goto('/maps/new')
  await page.getByLabel('여행 제목').fill(title)
  await pickDate(page, '시작일', isoDate(30))
  await pickDate(page, '종료일', isoDate(31))
  await page.getByRole('button', { name: '지도 만들기' }).click()
  await page.getByRole('button', { name: '나중에 할게요' }).click()
}

/** 초대 링크를 만든다. 화면의 「친구 초대하기」는 링크를 클립보드나 공유 창으로 넘겨서, 링크는 같은 API로 받는다. */
export async function inviteUrl(owner: Page): Promise<string> {
  const res = await owner.request.post(`${API_URL}/maps/${mapIdOf(owner)}/invite`)
  expect(res.ok()).toBeTruthy()
  return (await res.json()).url
}

/** 자체 장소 DB의 장소를 검색해 핀을 찍는다(「핀 찍기」. DB에 없는 곳은 「핀 남기기」다). */
export async function pinPlace(page: Page, name: string) {
  await page.getByRole('searchbox', { name: '장소 검색' }).fill(name)
  await page.getByRole('button', { name: '검색', exact: true }).click()
  await page.getByRole('listitem').filter({ hasText: name }).getByRole('button', { name: '핀 찍기' }).click()
  await expect(page.getByRole('status').filter({ hasText: name }).filter({ hasText: '지도에 찍었어요' })).toBeVisible()
}

/** 열린 핀 상세에서 🚫와 사유 칩을 고르고 등록한다. */
export async function opposeWithChip(page: Page, chip: string) {
  await page.getByRole('radio', { name: '반대' }).click()
  await page.getByRole('button', { name: chip, exact: true }).click()
  await page.getByRole('button', { name: '반대 남기기' }).click()
  // 토스트 글자만 맞춘다. 다 남기면 뜨는 완료 카드("모든 핀에 의견을 남겼어요", #1659)도 status라 함께 걸린다.
  await expect(page.getByRole('status').filter({ hasText: /^의견을 남겼어요$/ })).toBeVisible()
}

/** 「핀 찍기」 목록의 핀 줄. 접근성 이름이 「장소 이름 …」으로 시작한다. */
export function pinRow(page: Page, name: string) {
  // 반응 안 한 핀 줄 옆의 바로 반응 버튼(「○○ 좋음」, 「○○ 반대, 이유 쓰기」, #1696)도 이름이 같은 말로 시작해서 뺀다.
  return page.getByRole('main', { name: '바텀시트' }).getByRole('button', { name: new RegExp(`^${name} (?!좋음$|반대, 이유 쓰기$)`) })
}

/** 열린 핀 상세에서 「확정 리스트에 넣기」를 누른다. */
export async function confirmPin(page: Page, name: string) {
  // 일정을 다시 받기 전에 바로 날짜에 넣어도 저장돼야 한다(#1436) — 응답을 기다리지 않고 사람보다 빠르게 누른다.
  await page.getByRole('button', { name: '확정 리스트에 넣기', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: name }).filter({ hasText: '확정 리스트에 넣었어요' })).toBeVisible()
}

/** 내 크레딧(GET /credits/me). 가격과 잔액은 화면처럼 응답에서 읽는다 — 숫자를 테스트에 적지 않는다. */
export async function myCredits(page: Page): Promise<{ balance: number; max_balance: number; prices: Record<'recommend_run' | 'course', number> }> {
  const res = await page.request.get(`${API_URL}/credits/me`)
  expect(res.ok()).toBeTruthy()
  return res.json()
}
