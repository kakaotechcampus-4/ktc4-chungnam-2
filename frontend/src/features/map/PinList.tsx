import { useEffect, useRef, type ReactNode } from 'react'

import { useMeQuery } from '@/features/auth/queries'
import CategoryIcon from '@/ui/CategoryIcon'
import Mark from '@/ui/Mark'

import { participationRatio, toPinCard, type Pin, type PinCardView, type ReactionType } from './model'
import { attachTrashDrag } from './pinDrag'
import { createPinMarkerElement } from './pinMarker'
import UnknownName from '@/ui/UnknownName'

/** 반응 용어·기호는 고정(기획안 9절). 색은 지도 밖 UI 전용 반응 토큰(colors.md). */
const REACTION: Record<ReactionType | 'unknown', { mark: ReactNode; label: string; color: string; chip: string }> = {
  like: { mark: <Mark kind="like" size={12} />, label: '좋음', color: 'text-[var(--good-line)]', chip: 'border-[var(--good-line)] bg-[var(--good-bg)] text-[var(--good-text)]' },
  against: { mark: <Mark kind="against" size={12} />, label: '반대', color: 'text-[var(--bad-line)]', chip: 'border-[var(--bad-line)] bg-[var(--bad-bg)] text-[var(--bad-text)]' },
  unknown: { mark: <Mark kind="unknown" size={12} />, label: '미확인', color: 'text-ink-500', chip: '' },
}
const ORDER = ['like', 'against', 'unknown'] as const

/** 마지막으로 본 뒤 새로 생긴 것(#1454) — 카드에 「새 핀」 태그와 새 의견 줄로 단다. */
export type CardNews = { newPin: boolean; lines: string[] }

/** 핀 찍기 탭 목록(Figma 5절 마킹된 장소). "마킹됨" 배지는 넣지 않는다 — 여기엔 마킹된 장소만 올라온다. */
export default function PinList({
  pins,
  memberCount,
  onSelect,
  news,
}: {
  pins: Pin[]
  memberCount: number
  onSelect: (pinId: string) => void
  news?: Map<string, CardNews>
}) {
  const myId = useMeQuery().data?.id
  return (
    <ul className="space-y-2.5 pb-[100px]">
      {pins.map((pin) => (
        <li key={pin.id}>
          <PinCard
            card={toPinCard(pin, memberCount, myId)}
            news={news?.get(pin.id)}
            onSelect={() => onSelect(pin.id)}
            drag={pin.permissions.can_delete ? { pin, memberCount } : null}
          />
        </li>
      ))}
    </ul>
  )
}

/**
 * 아직 의견을 안 남긴 카드는 흰 바탕 + 파란 테두리 + 「의견 남기기」로 할 일을 보여준다(할 일 표시는 브랜드 파랑만).
 * 확정된 카드는 같은 자리에 골드 테두리 + 「✓ 확정됨」이다. 의견을 안 남겼어도 확정 표시가 먼저다(#859).
 * 내가 고른 반응은 그 반응 색 칩으로 감싸고 "· 나"를 붙인다 — "내 선택" 배지는 쓰지 않는다.
 */
function PinCard({
  card,
  news,
  onSelect,
  drag,
}: {
  card: PinCardView
  news?: CardNews
  onSelect: () => void
  drag: { pin: Pin; memberCount: number } | null
}) {
  const ref = useTrashDrag(drag)
  const todo = !card.confirmed && card.mine === null
  const border = card.confirmed
    ? 'border-[1.5px] border-[var(--pin-confirmed)]'
    : todo
      ? 'border-[1.5px] border-brand-600'
      : 'border border-ink-200'
  return (
    // 카테고리는 왼쪽 아이콘 칸으로 글자를 읽지 않고도 가른다(#1454). 지도 핀 모양은 그대로 둔다.
    <button ref={ref} type="button" onClick={onSelect} className={`press flex w-full gap-3 rounded-xl bg-surface p-3.5 text-left ${border}`}>
      <CategoryIcon category={card.category} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p className="flex min-w-0 items-center gap-1.5">
            <span className="truncate font-bold text-ink-900">{card.name}</span>
            {news?.newPin && <span className="tag tag-new">새 핀</span>}
          </p>
          {card.confirmed && (
            <span className="tag tag-confirmed">
              <Mark kind="check" size={12} /> 확정됨
            </span>
          )}
          {todo && (
            <span className="shrink-0 rounded-full bg-brand-50 px-2.5 py-0.5 text-xs font-semibold text-link">의견 남기기</span>
          )}
        </div>
        <p className="mt-0.5 text-xs text-ink-500"><UnknownName text={card.meta} /></p>
        <ReactionCounts card={card} className="mt-1.5" />
        {news && news.lines.length > 0 && (
          <ul className="mt-1.5 space-y-0.5 rounded-md bg-brand-50 px-2 py-1 text-xs text-selected">
            {news.lines.map((line) => (
              <li key={line} className="break-keep">
                새 의견 · {line}
              </li>
            ))}
          </ul>
        )}
      </div>
    </button>
  )
}

/** 좋음, 반대, 미확인 수 한 줄. 핀 찍기 목록 카드와 AI 코스 날짜별 카드가 같이 쓴다. */
export function ReactionCounts({ card, className = '' }: { card: Pick<PinCardView, 'counts' | 'mine'>; className?: string }) {
  return (
    <p className={`flex items-center gap-2 text-xs ${className}`} aria-label={summaryLabel(card)}>
      {ORDER.map((type) => {
        const r = REACTION[type]
        const mine = card.mine === type
        return (
          <span
            key={type}
            aria-hidden="true"
            className={`flex items-center gap-0.5 ${mine ? `rounded-sm border px-1.5 font-semibold ${r.chip}` : ''}`}
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
  )
}

function summaryLabel(card: Pick<PinCardView, 'counts' | 'mine'>) {
  const parts = ORDER.map((t) => `${REACTION[t].label} ${card.counts[t]}`)
  return `${parts.join(', ')}${card.mine ? `, 내 의견 ${REACTION[card.mine].label}` : ', 아직 의견 없음'}`
}

/**
 * 카드를 끌어 휴지통에 버린다(#1012, 지도 핀과 같은 함수). 끄는 그림은 지도에 그려진 그 핀 모양이다.
 * 붙인 뒤 바뀐 핀은 최신 값을 쓰도록 ref 로 둔다 — 의견이 달릴 때마다 다시 붙이면 끄는 도중 끊긴다.
 */
function useTrashDrag(drag: { pin: Pin; memberCount: number } | null) {
  const ref = useRef<HTMLButtonElement>(null)
  const latest = useRef(drag)
  useEffect(() => {
    latest.current = drag
  })
  const on = drag !== null
  useEffect(() => {
    const el = ref.current
    if (!el || !on) return
    const now = () => latest.current!
    return attachTrashDrag(
      el,
      () => now().pin,
      () => createPinMarkerElement(now().pin, participationRatio(now().pin, now().memberCount), () => {}).innerHTML,
    )
  }, [on])
  return ref
}
