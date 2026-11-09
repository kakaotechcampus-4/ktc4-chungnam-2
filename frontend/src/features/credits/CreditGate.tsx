import type { ReactNode } from 'react'
import { Link } from 'react-router'

import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import Coin from '@/ui/Coin'
import Notice from '@/ui/Notice'
import Sentences from '@/ui/Sentences'

import { adButtonText, adOfferText, balanceText, creditBlock, guestCreditText, insufficientText, type CreditFeature } from './model'
import { useCreditsQuery } from './queries'
import { useAdCharge } from './useAdCharge'

/**
 * 크레딧을 쓰는 AI 실행 버튼의 자리(「추천받기」·「코스 짜기」, #432). `children` 이 그 버튼이다.
 * - 게스트: 버튼 대신 처음부터 카카오 전환 안내. 게스트임은 GET /credits/me 의 403 으로 안다(숫자도 그 detail 에서).
 * - 잔액 부족(실행이 402): 안내 + 「후기 쓰러 가기」(확정 탭). 버튼은 둔다 — 후기를 쓰고 오면 다시 누를 수 있다.
 *   ad.available 이고 광고가 준비됐으면 고지 한 줄 + 「광고 보고 N 크레딧 받기」(#1039, 3.7). 받으면 onCharged.
 * - 그 밖: 버튼 오른쪽 칸에 동전 + 「N 크레딧 사용」(동전 색) / 「남은 크레딧 M/30」(상한은 응답의 max_balance).
 * 잔액이 가격보다 적은지는 화면이 미리 판단하지 않는다 — 판정은 서버(402) 한 곳이다.
 * `error` 는 그 실행 요청의 오류다. 크레딧과 무관한 오류는 부르는 쪽이 보인다(creditBlock 이 null).
 */
export default function CreditGate({
  feature,
  mapId,
  error,
  onReview,
  onCharged,
  children,
}: {
  feature: CreditFeature
  mapId: string
  error: unknown
  /** 「후기 쓰러 가기」를 누를 때 함께 할 일(예: 코스 시트 닫기). */
  onReview?: () => void
  /**
   * 광고로 크레딧을 받은 뒤 부른다. 안내는 실행 요청의 402 에서 오므로 부르는 쪽이 그 오류를 지운다(create.reset).
   * 화면이 잔액으로 「이제 충분하다」를 판단하지 않는다 — 다시 누르면 서버가 판정한다.
   */
  onCharged?: () => void
  children: ReactNode
}) {
  const credits = useCreditsQuery()
  const block = creditBlock(credits.error) ?? creditBlock(error)
  const ad = credits.data?.ad
  const charge = useAdCharge({ ad, enabled: block?.kind === 'insufficient', onCharged })

  if (block?.kind === 'guest') return <GuestAccountNotice>{guestCreditText(block.initialCredits)}</GuestAccountNotice>

  return (
    <div className="space-y-1.5">
      {block?.kind === 'insufficient' && (
        <Notice
          action={
            <>
              {/* 누르기 전에 무엇을 보면 무엇을 받는지 알린다(구글 보상형 광고 정책). 버튼은 서버의 available 로만 띄운다. */}
              {ad && charge.ready && <p className="text-xs text-ink-600">
                  <Sentences text={adOfferText(ad)} />
                </p>}
              <div className="flex flex-wrap gap-2">
                {ad && charge.ready && (
                  <button type="button" disabled={charge.busy} onClick={() => void charge.start()} className="btn-outline btn-sm">
                    {charge.busy ? '크레딧 받는 중…' : adButtonText(ad)}
                  </button>
                )}
                <Link to={`/maps/${mapId}/shortlist`} onClick={onReview} className="btn-outline btn-sm">
                  후기 쓰러 가기
                </Link>
              </div>
            </>
          }
        >
          {insufficientText(credits.data?.review_reward)}
        </Notice>
      )}
      {/* 버튼 오른쪽 칸에 쓸 크레딧과 남은 크레딧을 둔다 — 누르기 전에 눈에 들어오게(버튼 아래 작은 한 줄은 놓쳤다). */}
      {/* 잔액을 못 받아도 버튼은 막지 않는다 — 최종 판정은 서버다. 숫자는 응답에서만 읽는다(#733). */}
      <div className="flex gap-2">
        <div className="min-w-0 flex-1">{children}</div>
        {credits.data && (
          <div className="flex h-13 shrink-0 flex-col justify-center rounded-xl border border-ink-200 bg-white px-3">
            <p className="flex items-center gap-1 text-sm font-bold text-coin-text">
              <Coin size={16} />
              {credits.data.prices[feature]} 크레딧 사용
            </p>
            <p className="text-xs text-ink-600">{balanceText(credits.data)}</p>
          </div>
        )}
      </div>
      {credits.error && <p className="text-center text-xs text-ink-500">남은 크레딧을 불러오지 못했어요</p>}
    </div>
  )
}
