// 핵심 흐름(#1281, 기획안 3절): 지도 만들기 → 구성원 참여 → 핀 → 🚫 사유 → 추천 받기 → 「지도에 올리기」.
// 방장과 구성원 두 브라우저로 돌고, 구성원 화면은 끝까지 새로고침하지 않는다 — 실시간(SSE)으로 받아야 통과한다.
import { createMap, expect, inviteUrl, mapIdOf, opposeWithChip, pinPlace, pinRow, test } from './fixtures'

const OPPOSED = '성수 매운집'

test('방장이 반대한 곳을 빼고 추천받아 지도에 올리면 구성원이 새로고침 없이 본다', async ({ owner, member }) => {
  await test.step('방장이 지도를 만든다', async () => {
    await createMap(owner, 'E2E 성수 여행')
    await expect(owner).toHaveURL(/\/maps\/[0-9a-f-]+/)
  })

  await test.step('구성원이 초대 링크로 들어온다', async () => {
    await member.goto(await inviteUrl(owner))
    await expect(member.getByRole('heading', { name: 'E2E 성수 여행' })).toBeVisible()
    await member.getByRole('button', { name: '참여하기' }).click()
    await expect(member).toHaveURL(new RegExp(`/maps/${mapIdOf(owner)}`))
    await expect(member.getByRole('heading', { name: 'E2E 성수 여행에 참여했어요' })).toBeVisible()
    await member.getByRole('button', { name: '알겠어요' }).click()
    await expect(member.getByRole('heading', { name: '마킹된 장소' })).toBeVisible()
  })

  await test.step('방장이 핀을 찍고 사유와 함께 반대한다', async () => {
    await pinPlace(owner, OPPOSED)
    await opposeWithChip(owner, '매워요')
    await expect(pinRow(owner, OPPOSED)).toHaveAccessibleName(/반대 1/)
  })

  await test.step('구성원 화면에 핀과 반대가 실시간으로 뜬다', async () => {
    await expect(pinRow(member, OPPOSED)).toHaveAccessibleName(/반대 1/)
  })

  let picked = ''
  await test.step('방장이 음식점 추천을 받는다', async () => {
    await owner.getByRole('link', { name: 'AI 추천' }).click()
    await owner.getByRole('button', { name: '음식점 추천받기' }).click()
    await expect(owner.getByText(/음식점 대안 \d곳을 찾았어요/)).toBeVisible({ timeout: 30_000 })
    await expect(owner.getByText('나에게만 보여요', { exact: false })).toBeVisible()

    const cards = owner.getByRole('article')
    const count = await cards.count()
    expect(count).toBeGreaterThanOrEqual(1)
    expect(count).toBeLessThanOrEqual(3)
    // 이미 지도에 있는 곳(반대한 곳)은 후보가 아니다(가드레일 6)
    await expect(cards.filter({ hasText: OPPOSED })).toHaveCount(0)
    // 후보마다 조건별 충족과 출처가 붙는다(가드레일 5)
    for (const card of await cards.all()) {
      await expect(card).toContainText('조건 충족')
      await expect(card).toContainText('출처')
    }
    picked = (await cards.first().getByRole('heading', { level: 3 }).getByRole('button').innerText()).trim()
  })

  await test.step('올리기 전 후보는 구성원에게 보이지 않는다(가드레일 1)', async () => {
    await expect(pinRow(member, OPPOSED)).toBeVisible()
    await expect(pinRow(member, picked)).toHaveCount(0)
  })

  await test.step('방장이 첫 후보를 지도에 올린다', async () => {
    const card = owner.getByRole('article').filter({ has: owner.getByRole('heading', { name: new RegExp(`^${picked} `) }) })
    await card.getByRole('button', { name: '지도에 올리기' }).click()
    await expect(card).toContainText('지도에 올렸어요')
  })

  await test.step('구성원 화면에 올린 핀이 실시간으로 뜬다', async () => {
    await expect(pinRow(member, picked)).toBeVisible()
  })
})
