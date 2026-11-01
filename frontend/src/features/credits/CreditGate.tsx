import type { ReactNode } from 'react'
import { Link } from 'react-router'

import GuestAccountNotice from '@/features/auth/GuestAccountNotice'
import Notice from '@/ui/Notice'

import { creditBlock, guestCreditText, insufficientText, type CreditFeature } from './model'
import { useCreditsQuery } from './queries'

/**
 * 크레딧을 쓰는 AI 실행 버튼의 자리(「추천받기」·「코스 짜기」, #432). `children` 이 그 버튼이다.
 * - 게스트: 버튼 대신 처음부터 카카오 전환 안내. 게스트임은 GET /credits/me 의 403 으로 안다(숫자도 그 detail 에서).
 * - 잔액 부족(실행이 402): 안내 + 「후기 쓰러 가기」(확정 탭). 버튼은 둔다 — 후기를 쓰고 오면 다시 누를 수 있다.
 * - 그 밖: 버튼 아래 「N 크레딧 사용 · 남은 크레딧 M」.
 * 잔액이 가격보다 적은지는 화면이 미리 판단하지 않는다 — 판정은 서버(402) 한 곳이다.
 * `error` 는 그 실행 요청의 오류다. 크레딧과 무관한 오류는 부르는 쪽이 보인다(creditBlock 이 null).
 */
export default function CreditGate({
  feature,
  mapId,
  error,
  onReview,
  children,
}: {
  feature: CreditFeature
  mapId: string
  error: unknown
  /** 「후기 쓰러 가기」를 누를 때 함께 할 일(예: 코스 시트 닫기). */
  onReview?: () => void
  children: ReactNode
}) {
  const credits = useCreditsQuery()
  const block = creditBlock(credits.error) ?? creditBlock(error)

  if (block?.kind === 'guest') return <GuestAccountNotice>{guestCreditText(block.initialCredits)}</GuestAccountNotice>

  return (
    <div className="space-y-1.5">
      {block?.kind === 'insufficient' && (
        <Notice
          action={
            <Link to={`/maps/${mapId}/shortlist`} onClick={onReview} className="btn-outline btn-sm">
              후기 쓰러 가기
            </Link>
          }
        >
          {insufficientText(credits.data?.review_reward)}
        </Notice>
      )}
      {children}
      {/* 잔액을 못 받아도 버튼은 막지 않는다 — 최종 판정은 서버다. 숫자는 응답에서만 읽는다(#733). */}
      <p className="text-center text-label text-ink-500">
        {credits.data
          ? `${credits.data.prices[feature]} 크레딧 사용 · 남은 크레딧 ${credits.data.balance}`
          : credits.error
            ? '남은 크레딧을 불러오지 못했어요'
            : ' '}
      </p>
    </div>
  )
}
