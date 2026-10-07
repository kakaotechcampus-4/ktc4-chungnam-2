import type { ReactNode } from 'react'

import { useMeQuery } from '@/features/auth/queries'
import AgainstMark from '@/ui/AgainstMark'

import { toPinCard, type Pin, type PinCardView, type ReactionType } from './model'

/** 반응 용어·기호는 고정(기획안 9절). 색은 지도 밖 UI 전용 반응 토큰(colors.md). */
const REACTION: Record<ReactionType | 'unknown', { mark: ReactNode; label: string; color: string; chip: string }> = {
  like: { mark: '♥', label: '좋음', color: 'text-[var(--good-line)]', chip: 'border-[var(--good-line)] bg-[var(--good-bg)] text-[var(--good-text)]' },
  against: { mark: <AgainstMark size={12} />, label: '반대', color: 'text-[var(--bad-line)]', chip: 'border-[var(--bad-line)] bg-[var(--bad-bg)] text-[var(--bad-text)]' },
  unknown: { mark: '?', label: '미확인', color: 'text-ink-500', chip: '' },
}
const ORDER = ['like', 'against', 'unknown'] as const

/** 마킹된 장소 목록(Figma 5절). "마킹됨" 배지는 넣지 않는다 — 여기엔 마킹된 장소만 올라온다. */
export default function PinList({
  pins,
  memberCount,
  onSelect,
}: {
  pins: Pin[]
  memberCount: number
  onSelect: (pinId: string) => void
}) {
  const myId = useMeQuery().data?.id
  return (
    <ul className="space-y-2.5 pb-[100px]">
      {pins.map((pin) => (
        <li key={pin.id}>
          <PinCard card={toPinCard(pin, memberCount, myId)} onSelect={() => onSelect(pin.id)} />
        </li>
      ))}
    </ul>
  )
}

/**
 * 아직 의견을 안 남긴 카드는 흰 바탕 + 파란 테두리 + 「의견 남기기」로 할 일을 보여준다(할 일 표시는 브랜드 파랑만).
 * 내가 고른 반응은 그 반응 색 칩으로 감싸고 "· 나"를 붙인다 — "내 선택" 배지는 쓰지 않는다.
 */
function PinCard({ card, onSelect }: { card: PinCardView; onSelect: () => void }) {
  const todo = card.mine === null
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-xl p-3.5 text-left ${todo ? 'border-[1.5px] border-brand-600 bg-white' : 'border border-ink-200 bg-white'}`}
    >
      <div className="flex items-start justify-between gap-2">
        <p className="truncate font-bold text-ink-900">{card.name}</p>
        {todo && (
          <span className="shrink-0 rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-brand-600">의견 남기기</span>
        )}
      </div>
      <p className="mt-0.5 text-xs text-ink-500">{card.meta}</p>
      <p className="mt-1.5 flex items-center gap-2 text-xs" aria-label={summaryLabel(card)}>
        {ORDER.map((type) => {
          const r = REACTION[type]
          const mine = card.mine === type
          return (
            <span
              key={type}
              aria-hidden="true"
              className={`flex items-center gap-0.5 ${mine ? `rounded-md border px-1.5 font-semibold ${r.chip}` : ''}`}
            >
              <span className={mine ? '' : r.color}>{r.mark}</span>
              <span className={mine ? '' : 'text-ink-700'}>
                {card.counts[type]}
                {mine && ' · 나'}
              </span>
            </span>
          )
        })}
      </p>
    </button>
  )
}

function summaryLabel(card: PinCardView) {
  const parts = ORDER.map((t) => `${REACTION[t].label} ${card.counts[t]}`)
  return `${parts.join(', ')}${card.mine ? `, 내 의견 ${REACTION[card.mine].label}` : ', 아직 의견 없음'}`
}

/** 불러오는 중(Figma '불러오는 중') — 카드 모양 자리만 먼저 보여준다. */
export function PinListSkeleton() {
  return (
    <ul className="space-y-2.5" aria-hidden="true">
      {[0, 1, 2].map((i) => (
        <li key={i} className="animate-pulse space-y-2 rounded-xl border border-ink-200 p-3.5">
          <div className="h-4 w-2/3 rounded bg-ink-100" />
          <div className="h-3 w-1/2 rounded bg-ink-100" />
          <div className="h-3 w-1/3 rounded bg-ink-100" />
        </li>
      ))}
    </ul>
  )
}
