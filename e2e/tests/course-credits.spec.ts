// AI 코스와 크레딧(#1424). 목 서버로 도는 화면 테스트가 못 보는 곳 — 코스 결과의 「반영」이 실제 일정 API에 저장되는지(#1388에서
// develop을 합치며 깨졌다), 크레딧 차감과 잔액 부족(402)이 서버 판정대로 화면에 오는지 — 를 실제 백엔드로 본다.
// 모델은 스텁(LLM_MODE=dev)이라 코스는 코드 기준선이 짠다. 크레딧 숫자는 응답에서 읽는다(#733).
import { confirmPin, createMap, expect, myCredits, opposeWithChip, pinPlace, test } from './fixtures'

const PLACES = ['성수 한식집', '성수 횟집', '성수 분식집']

test('확정 장소 하나만 날짜에 넣고 코스를 짜면, 남은 곳을 한 번에 일정에 넣고 크레딧을 쓴다', async ({ planner }) => {
  const before = await myCredits(planner)
  const price = before.prices.course

  await test.step('지도를 만들고 세 곳을 확정 리스트에 넣는다', async () => {
    await createMap(planner, 'E2E 코스 여행')
    for (const name of PLACES) {
      await pinPlace(planner, name)
      await confirmPin(planner, name)
    }
  })

  await test.step('확정 탭에서 한 곳만 첫째 날에 넣는다', async () => {
    await planner.getByRole('link', { name: '확정된 장소' }).click()
    await planner.getByRole('checkbox', { name: `${PLACES[0]} 고르기` }).check()
    await planner.getByRole('button', { name: '1곳 넣기' }).click()
    await expect(planner.getByText('3곳 · 일정에 넣은 곳 1')).toBeVisible()
  })

  await test.step('AI 코스에서 쓸 크레딧과 남은 크레딧을 확인하고 코스를 짠다', async () => {
    await planner.getByRole('link', { name: 'AI 코스' }).click()
    await planner.getByRole('button', { name: '코스 짜기', exact: true }).click()
    const dialog = planner.getByRole('alertdialog')
    await expect(dialog).toContainText(`${price} 크레딧을 써요`)
    await expect(dialog).toContainText(`남은 크레딧 ${before.balance}/${before.max_balance}`)
    await dialog.getByRole('button', { name: '코스 짜기' }).click()
    // 일부만 넣은 일정은 fill — 넣어 둔 곳은 그대로 두고 남은 두 곳에 「○일째에 넣기」 카드가 붙는다(#1322)
    await expect(planner.getByText(/남은 2곳을 나눠 봤어요/)).toBeVisible({ timeout: 60_000 })
  })

  await test.step('「남은 곳 한 번에 넣기」를 누르면 일정에 저장된다', async () => {
    await planner.getByRole('button', { name: '남은 2곳 한 번에 넣기' }).click()
    await expect(planner.getByText('반영했어요')).toHaveCount(2)
    await planner.getByRole('link', { name: '확정된 장소' }).click()
    await expect(planner.getByText(/모든 장소를 일정에 넣었어요/)).toBeVisible()
  })

  await test.step('크레딧이 코스 한 번 값만큼 줄었다', async () => {
    await planner.getByRole('link', { name: 'AI 코스' }).click()
    await planner.getByRole('button', { name: '닫기' }).click()
    await expect(planner.getByText(`${price} 크레딧 사용 · 남은 크레딧 ${before.balance - price}/${before.max_balance}`)).toBeVisible()
  })
})

test('크레딧이 0이면 추천받기를 눌렀을 때 서버의 잔액 부족에 맞춰 후기 안내를 띄우고 추천하지 않는다', async ({ broke }) => {
  await createMap(broke, 'E2E 크레딧 없음')
  await pinPlace(broke, '성수 매운집')
  await opposeWithChip(broke, '매워요')

  await broke.getByRole('link', { name: 'AI 추천' }).click()
  await broke.getByRole('button', { name: '음식점 추천받기' }).click()
  // 화면은 잔액으로 미리 막지 않는다 — 판정은 서버(402) 한 곳이다(CreditGate)
  await broke.getByRole('alertdialog').getByRole('button', { name: '추천받기' }).click()
  await expect(broke.getByText(/크레딧이 부족해요/)).toBeVisible()
  await expect(broke.getByRole('link', { name: '후기 쓰러 가기' })).toBeVisible()
  await expect(broke.getByText(/대안 \d곳을 찾았어요/)).toHaveCount(0)
  expect((await myCredits(broke)).balance).toBe(0)
})
