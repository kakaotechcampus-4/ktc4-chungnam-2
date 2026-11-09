import { CircleHelp } from 'lucide-react'

import { FAQ } from '@/features/help/faq'
import WelcomeScene from '@/features/onboarding/WelcomeScene'
import MenuPopover from '@/features/shell/MenuPopover'
import Coin from '@/ui/Coin'
import Sentences from '@/ui/Sentences'

import { balanceText, type CreditBalanceDto } from './model'

/** 설명 풍선은 자주 묻는 질문의 크레딧 답과 같은 그림·글이다 — 글을 두 곳에 적지 않는다. */
const CREDITS_FAQ = FAQ.find((f) => f.id === 'credits')

/**
 * AI 실행 버튼 오른쪽의 크레딧 글(DESIGN.md 「크레딧 동전」). 동전 + 「N 크레딧 사용」 / 「남은 크레딧 M/30」.
 * 크레딧을 쓰지 않는 실행(다시 추천)은 `cost` 0 — 「크레딧 안 써요」. 숫자는 GET /credits/me 응답 그대로다(#733).
 * 테두리 없는 글이고, 누르면(터치·클릭 같게, 호버는 휴대폰에 없어 쓰지 않는다) 크레딧 설명 풍선이 뜬다 —
 * 움직이는 그림(FAQ 크레딧 장면) + 한 문단. 「?」가 누를 수 있다는 표시다(ReactionHelp 와 같은 기호).
 */
export default function CreditBox({ cost, credits }: { cost: number; credits: Pick<CreditBalanceDto, 'balance'> & { max_balance?: number } }) {
  return (
    <MenuPopover
      label="크레딧 설명"
      trigger={
        <button type="button" className="press flex shrink-0 flex-col justify-center rounded-xl px-2 text-left">
          <span className="flex items-center gap-1 text-sm font-bold text-coin-text">
            <Coin size={16} />
            {cost ? `${cost} 크레딧 사용` : '크레딧 안 써요'}
            <CircleHelp size={14} aria-hidden="true" className="text-ink-400" />
          </span>
          <span className="text-xs text-ink-600">{balanceText(credits)}</span>
          <span className="sr-only">, 크레딧 설명 보기</span>
        </button>
      }
    >
      {CREDITS_FAQ && (
        <>
          <WelcomeScene kind={CREDITS_FAQ.scene} />
          <p className="mt-3 text-sm font-bold text-ink-900">{CREDITS_FAQ.q}</p>
          <p className="mt-1 break-keep text-body text-ink-700">
            <Sentences text={CREDITS_FAQ.a} />
          </p>
        </>
      )}
    </MenuPopover>
  )
}
