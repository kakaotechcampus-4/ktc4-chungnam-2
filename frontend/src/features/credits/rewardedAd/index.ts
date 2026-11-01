import type { CreditAdDto } from '../model'

/**
 * 보상형 광고 제공자를 한 모양으로 감싼다(#1039, docs/credits-reviews.md 3.7).
 * 어느 제공자를 쓸지와 광고 단위는 서버가 GET /credits/me 의 ad.provider·ad.unit_id 로 내린다 — 빌드 변수에 두지 않는다.
 *
 * - load 가 null 이면 채울 광고가 없다 → 버튼을 띄우지 않는다(알리지 않는다, 광고가 없는 것은 실패가 아니다).
 * - load 가 실패(reject)하면 「광고를 불러오지 못했어요」.
 * - LoadedAd 는 한 번 보이면 끝이다. 다시 보이려면 load 를 다시 부른다(실제 보상형 광고도 슬롯을 한 번만 쓴다).
 */
export type AdOutcome = 'viewed' | 'dismissed' | 'error'

export type LoadedAd = {
  /**
   * 광고를 띄우고, 사람이 닫으면 결과를 돌려준다. viewed = 끝까지 봤다, dismissed = 그 전에 닫았다.
   * seconds 는 서버가 보상을 줄 수 있을 때까지 남은 시간(AdSession.claim_after_s)이다.
   * 테스트 광고는 이 길이로 센다. 실제 광고는 제 길이가 있어 쓰지 않는다.
   */
  show: (opts: { seconds: number }) => Promise<AdOutcome>
}

export type AdProvider = NonNullable<CreditAdDto['provider']>

// 광고 단위(_unitId)는 실제 제공자(adsense·gpt)를 채울 때 쓴다.
export async function load(provider: CreditAdDto['provider'], _unitId: CreditAdDto['unit_id']): Promise<LoadedAd | null> {
  switch (provider) {
    case 'fake':
      // 테스트 광고 창은 화면을 그리는 코드라 처음 쓸 때만 불러온다.
      return (await import('./fake')).loadFakeAd()
    // 실제 광고는 광고 계정이 열린 뒤 채운다(adsbygoogle.js·gpt.js 는 이 PR 에서 넣지 않는다). 그전에는 버튼이 보이지 않는다.
    case 'adsense':
    case 'gpt':
      return null
    default:
      return null
  }
}
