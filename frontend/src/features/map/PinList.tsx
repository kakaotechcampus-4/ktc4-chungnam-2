import { useEffect, useRef, type ReactNode } from 'react'

import { useMeQuery } from '@/features/auth/queries'
import { showToast } from '@/features/shell/toast'
import CategoryIcon from '@/ui/CategoryIcon'
import Mark from '@/ui/Mark'

import { isTodo, participationRatio, toPinCard, type Pin, type PinCardView, type ReactionType } from './model'
import { attachTrashDrag } from './pinDrag'
import { createPinMarkerElement } from './pinMarker'
import { useMyReactionMutation } from './queries'
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

/**
 * 핀 찍기 탭 목록(Figma 5절 마킹된 장소). "마킹됨" 배지는 넣지 않는다 — 여기엔 마킹된 장소만 올라온다.
 * `todoIds`를 주면 "의견 남길 핀"을 맨 위에 묶고 나머지를 그 아래에 둔다(#1696). 묶음은 부르는 쪽이 순서를 정할 때 같이 정해
 * 고정한다 — 목록에서 ♥를 누른 카드가 바로 아래 묶음으로 튀지 않고 그 자리에서 '남김' 모양으로만 바뀐다(#308과 같은 이유).
 */
export default function PinList({
  mapId,
  pins,
  memberCount,
  onSelect,
  news,
  todoIds,
}: {
  mapId: string
  pins: Pin[]
  memberCount: number
  onSelect: (pinId: string, opts?: { against?: boolean }) => void
  news?: Map<string, CardNews>
  todoIds?: ReadonlySet<string>
}) {
  const myId = useMeQuery().data?.id
  const item = (pin: Pin) => (
    <li key={pin.id}>
      <PinCard
        mapId={mapId}
        pin={pin}
        card={toPinCard(pin, memberCount, myId)}
        news={news?.get(pin.id)}
        onSelect={(opts) => onSelect(pin.id, opts)}
        drag={pin.permissions.can_delete ? { pin, memberCount } : null}
      />
    </li>
  )
  const todo = todoIds ? pins.filter((p) => todoIds.has(p.id)) : []
  const rest = todoIds ? pins.filter((p) => !todoIds.has(p.id)) : pins
  if (todo.length === 0 || rest.length === 0) return <ul className="space-y-2.5 pb-[100px]">{pins.map(item)}</ul>
  // 머리 숫자는 지금 남은 수다 — 묶음 안에서 의견을 남긴 카드는 자리는 지키되 세지 않는다.
  const left = todo.filter((p) => isTodo(p)).length
  return (
    <div className="space-y-5 pb-[100px]">
      <section aria-labelledby="todo-pins" className="space-y-2.5">
        <h3 id="todo-pins" className="text-sm font-bold text-ink-900">
          {left > 0 ? (
            <>
              의견 남길 핀 <span className="text-link">{left}</span>
            </>
          ) : (
            // 다 남겼다는 말은 위 완료 카드(MyOpinionProgress)가 한다 — 같은 말을 두 번 하지 않는다.
            '방금 의견을 남긴 핀'
          )}
        </h3>
        <ul className="space-y-2.5">{todo.map(item)}</ul>
      </section>
      <section aria-labelledby="rest-pins" className="space-y-2.5">
        <h3 id="rest-pins" className="text-sm font-bold text-ink-900">
          나머지 핀 <span className="font-normal text-ink-500">{rest.length}</span>
        </h3>
        <ul className="space-y-2.5">{rest.map(item)}</ul>
      </section>
    </div>
  )
}

/** 카드 면 — 할 일(연파랑), 확정(연골드), 나머지(흰 면). 할 일 표시는 브랜드 파랑만(DESIGN.md "파랑은 할 일 규칙"). */
const FACE = {
  todo: 'border-[1.5px] border-brand-600 bg-brand-50',
  confirmed: 'border-[1.5px] border-[var(--pin-confirmed)] bg-[var(--confirmed-bg)]',
  done: 'border border-ink-200 bg-surface',
} as const

/**
 * 핀 카드 한 장(#1696). 아직 의견을 안 남긴 카드(할 일)는 연파랑 면에 "♥ 좋음""✕ 반대" 버튼이 붙는다.
 * ♥는 그 자리에서 바로 등록하고(되돌리기 토스트), ✕는 사유가 있어야 등록되므로(가드레일 3) 상세를 반대가 골라진 채로 연다.
 * 확정 카드는 연골드 면 + "✓ 확정됨"이고, 의견을 안 남겼어도 확정이 먼저다(#859). 의견을 남긴 카드는 흰 면에 내 의견 태그다.
 * 카드 어디를 눌러도 상세가 열린다 — 이름 버튼이 카드 전체를 덮고(::before), 반응 버튼은 그 위에 올라온다.
 */
function PinCard({
  mapId,
  pin,
  card,
  news,
  onSelect,
  drag,
}: {
  mapId: string
  pin: Pin
  card: PinCardView
  news?: CardNews
  onSelect: (opts?: { against?: boolean }) => void
  drag: { pin: Pin; memberCount: number } | null
}) {
  const ref = useTrashDrag(drag)
  const todo = !card.confirmed && card.mine === null
  const face = card.confirmed ? FACE.confirmed : todo ? FACE.todo : FACE.done
  // 이름은 장소 이름으로 시작한다(e2e pinRow). 보이는 글자는 모두 이 이름에 담고 따로 읽히지 않게 숨긴다.
  const label = [`${card.name} ${card.meta}`, card.confirmed && '확정됨', news?.newPin && '새 핀', summaryLabel(card)].filter(Boolean).join(', ')
  return (
    // 카테고리는 왼쪽 아이콘 칸으로 글자를 읽지 않고도 가른다(#1454). 지도 핀 모양은 그대로 둔다.
    <article ref={ref} className={`press relative flex w-full gap-3 rounded-xl p-3.5 text-left ${face}`}>
      <CategoryIcon category={card.category} />
      <div className="min-w-0 flex-1">
        <div className="flex items-start justify-between gap-2">
          <p className="flex min-w-0 items-center gap-1.5">
            <button
              type="button"
              onClick={() => onSelect()}
              aria-label={label}
              className="truncate text-left font-bold text-ink-900 outline-none before:absolute before:inset-0 before:rounded-xl focus-visible:before:outline-2 focus-visible:before:outline-offset-2 focus-visible:before:outline-[var(--line-focus)]"
            >
              {card.name}
            </button>
            {news?.newPin && (
              <span aria-hidden="true" className="tag tag-new">
                새 핀
              </span>
            )}
          </p>
          {card.confirmed ? (
            <span aria-hidden="true" className="tag tag-confirmed">
              <Mark kind="check" size={12} /> 확정됨
            </span>
          ) : (
            card.mine && (
              <span aria-hidden="true" className={`tag ${card.mine === 'like' ? 'tag-good' : 'tag-bad'}`}>
                {REACTION[card.mine].mark} 내 의견 {REACTION[card.mine].label}
              </span>
            )
          )}
        </div>
        <p aria-hidden="true" className="mt-0.5 text-xs text-ink-500">
          <UnknownName text={card.meta} />
        </p>
        <ReactionCounts card={card} plain className="mt-1.5" />
        {todo && <QuickReact mapId={mapId} pin={pin} onAgainst={() => onSelect({ against: true })} />}
        {news && news.lines.length > 0 && (
          <ul className="mt-1.5 space-y-0.5 rounded-md bg-surface px-2 py-1 text-xs text-selected">
            {news.lines.map((line) => (
              <li key={line} className="break-keep">
                새 의견 · {line}
              </li>
            ))}
          </ul>
        )}
      </div>
    </article>
  )
}

/**
 * 할 일 카드의 바로 반응(#1696). "미확인"은 반응이 아니라 아직 안 남긴 사람 수라 버튼이 없다.
 * 버튼은 카드를 덮은 이름 버튼 위에 올라오고(relative z-10), 끌어서 버리기가 잡지 않게 data-no-drag 를 단다.
 * 버튼 이름은 반응을 앞에 둔다 — 카드 이름 버튼만 장소 이름으로 시작해야 장소로 카드를 찾을 수 있다(e2e pinRow).
 */
function QuickReact({ mapId, pin, onAgainst }: { mapId: string; pin: Pin; onAgainst: () => void }) {
  const react = useMyReactionMutation(mapId, pin)
  const name = pin.place_name ?? '이 장소'
  function like() {
    react.mutate(
      { type: 'like' },
      {
        onSuccess: () =>
          showToast('좋음을 남겼어요', {
            label: '되돌리기',
            onClick: () => react.mutate(null, { onError: () => showToast('의견을 되돌리지 못했어요') }),
          }),
        onError: () => showToast('의견을 등록하지 못했어요', { label: '다시 시도', onClick: like }),
      },
    )
  }
  return (
    <div data-no-drag className="relative z-10 mt-2.5 grid grid-cols-2 gap-1.5">
      <button type="button" onClick={like} disabled={react.isPending} aria-label={`좋음, ${name}`} className="btn-neutral btn-sm bg-surface">
        <span className={REACTION.like.color}>{REACTION.like.mark}</span> 좋음
      </button>
      <button type="button" onClick={onAgainst} aria-label={`반대 이유 쓰기, ${name}`} className="btn-neutral btn-sm bg-surface">
        <span className={REACTION.against.color}>{REACTION.against.mark}</span> 반대
      </button>
    </div>
  )
}

/** 좋음, 반대, 미확인 수 한 줄. 핀 찍기 목록 카드와 AI 코스 날짜별 카드가 같이 쓴다. */
export function ReactionCounts({ card, className = '', plain = false }: { card: Pick<PinCardView, 'counts' | 'mine'>; className?: string; plain?: boolean }) {
  // plain: 내 의견을 칩으로 감싸지 않고, 읽어 주기도 하지 않는다 — 핀 찍기 카드는 내 의견을 태그로 보이고 카드 이름에 다 담는다(#1696).
  return (
    <p className={`flex items-center gap-2 text-xs ${className}`} aria-label={plain ? undefined : summaryLabel(card)} aria-hidden={plain || undefined}>
      {ORDER.map((type) => {
        const r = REACTION[type]
        const mine = !plain && card.mine === type
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
  const ref = useRef<HTMLElement>(null)
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
