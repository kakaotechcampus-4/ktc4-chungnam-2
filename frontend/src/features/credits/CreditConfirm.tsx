import ConfirmDialog from '@/ui/ConfirmDialog'

import { balanceText, type CreditFeature } from './model'
import { useCreditsQuery } from './queries'

/**
 * 크레딧을 쓰는 AI 실행(「추천받기」·「코스 짜기」) 전에 묻는 창. 쓸 크레딧과 남은 크레딧을 보인다(2026-11-05).
 * 숫자는 GET /credits/me 응답 그대로다(#733). 잔액이 모자란지는 여기서 판단하지 않는다 — 판정은 서버(402)이고 안내는 CreditGate 가 한다.
 * 잔액을 못 받아도 막지 않는다.
 */
export default function CreditConfirm({
  feature,
  title,
  ok,
  onOk,
  onCancel,
}: {
  feature: CreditFeature
  title: string
  ok: string
  onOk: () => void
  onCancel: () => void
}) {
  const credits = useCreditsQuery()
  return (
    <ConfirmDialog
      title={title}
      detail={
        credits.data ? (
          <div className="space-y-1 text-ink-700">
            <p className="font-semibold text-ink-900">{credits.data.prices[feature]} 크레딧을 써요</p>
            <p>{balanceText(credits.data)}</p>
          </div>
        ) : undefined
      }
      body={credits.data ? undefined : credits.isPending ? '남은 크레딧을 확인하는 중이에요' : '남은 크레딧을 불러오지 못했어요'}
      ok={ok}
      onOk={onOk}
      onCancel={onCancel}
    />
  )
}
