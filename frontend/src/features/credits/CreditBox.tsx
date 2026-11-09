import Coin from '@/ui/Coin'

import { balanceText, type CreditBalanceDto } from './model'

/**
 * AI 실행 버튼 오른쪽에 붙는 크레딧 칸(DESIGN.md 「크레딧 동전」). 동전 + 「N 크레딧 사용」 / 「남은 크레딧 M/30」.
 * 크레딧을 쓰지 않는 실행(다시 추천)은 `cost` 0 — 「크레딧 안 써요」. 숫자는 GET /credits/me 응답 그대로다(#733).
 * 높이는 옆 버튼에 맞춰 늘어난다(부모 flex 의 stretch).
 */
export default function CreditBox({ cost, credits }: { cost: number; credits: Pick<CreditBalanceDto, 'balance'> & { max_balance?: number } }) {
  return (
    <div className="flex shrink-0 flex-col justify-center rounded-xl border border-ink-200 bg-white px-3 py-1">
      <p className="flex items-center gap-1 text-sm font-bold text-coin-text">
        <Coin size={16} />
        {cost ? `${cost} 크레딧 사용` : '크레딧 안 써요'}
      </p>
      <p className="text-xs text-ink-600">{balanceText(credits)}</p>
    </div>
  )
}
