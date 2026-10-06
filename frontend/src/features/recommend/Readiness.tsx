import { useState } from 'react'
import { Check, Share } from 'lucide-react'

import ErrorText from '@/ErrorText'
import { useShareInvite } from '@/features/maps/useShareInvite'
import AgainstMark from '@/ui/AgainstMark'
import Pingo from '@/ui/Pingo'

import { runErrorMessage, toReadinessCards, type ReadinessCard, type RecommendCategory } from './model'
import { useCreateRunMutation, useReadinessQuery } from './queries'

/** AI 탭 시트 머리글 — 화자는 핑고(colors.md 4절 3층). */
export function AiHeader({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl bg-[var(--pingo-bg)] p-3">
      <Pingo size={36} />
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 font-bold text-ink-900">
          <span className="rounded bg-brand-600 px-1.5 text-[0.6875rem] text-white">AI</span>
          {title}
        </p>
        <p className="text-xs text-ink-500">{sub}</p>
      </div>
    </div>
  )
}

/** 준비 판정(Figma 6절 '준비 미달'). 준비된 카테고리를 골라 「○○ 추천받기」. 한 화면의 채움 버튼은 이것 하나다. */
export function ReadinessBody({ mapId }: { mapId: string }) {
  const readiness = useReadinessQuery(mapId)
  const create = useCreateRunMutation(mapId)
  const cards = readiness.data ? toReadinessCards(readiness.data) : []
  const firstReady = cards.find((c) => c.ready)?.category ?? null
  const [picked, setPicked] = useState<RecommendCategory | null>(null)
  const chosen = picked && cards.find((c) => c.category === picked)?.ready ? picked : firstReady
  const required = cards[0]?.required ?? 0

  if (readiness.isPending) return <p className="text-sm text-ink-500">준비 상태를 확인하는 중…</p>
  if (readiness.error) return <ErrorText message="추천 준비 상태를 불러오지 못했어요" error={readiness.error} />

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-2">
        {cards.map((c, i) => (
          <ReadinessTile
            key={c.category}
            card={c}
            selected={c.category === chosen}
            wide={cards.length % 2 === 1 && i === cards.length - 1}
            onPick={() => setPicked(c.category)}
          />
        ))}
      </div>
      <p className="text-[0.6875rem] text-ink-500">* 의견 남긴 구성원이 {required}명(구성원 절반) 이상이면 추천 가능해요.</p>
      {create.error && <ErrorText message={runErrorMessage(create.error)} error={create.error} />}
      <button
        type="button"
        disabled={!chosen || create.isPending}
        onClick={() => chosen && create.mutate(chosen)}
        className="w-full rounded-xl bg-brand-600 py-3.5 font-bold text-white disabled:bg-ink-100 disabled:text-ink-400"
      >
        {create.isPending ? '조건을 모으는 중…' : chosen ? `${chosen} 추천받기` : '아직 추천할 수 있는 곳이 없어요'}
      </button>
    </div>
  )
}

function ReadinessTile({ card, selected, wide, onPick }: { card: ReadinessCard; selected: boolean; wide: boolean; onPick: () => void }) {
  const short = Math.max(0, card.required - card.answered)
  const pct = card.required ? Math.min(100, (card.answered / card.required) * 100) : 0
  return (
    <button
      type="button"
      disabled={!card.ready}
      aria-pressed={selected}
      onClick={onPick}
      className={`rounded-xl border-[1.5px] p-3 text-left ${wide ? 'col-span-2' : ''} ${
        selected ? 'border-brand-600 bg-brand-50' : card.ready ? 'border-[var(--good-line)] bg-white' : 'border-[var(--warn-line)] bg-[var(--warn-bg)]'
      }`}
    >
      <p className="flex items-center justify-between font-bold text-ink-900">
        <span className="flex items-center gap-1.5">
          {card.category}
          <span
            className={`rounded px-1.5 text-[0.625rem] text-white ${card.ready ? 'bg-[var(--good-line)]' : 'bg-[var(--warn-line)]'}`}
          >
            {card.ready ? '준비 완료' : '추가 필요'}
          </span>
        </span>
        {selected && <Check size={16} className="text-brand-600" aria-label="선택됨" />}
      </p>
      <div className="mt-2 h-1.5 rounded-full bg-ink-200">
        <div className={`h-full rounded-full ${card.ready ? 'bg-[var(--good-line)]' : 'bg-[var(--warn-line)]'}`} style={{ width: `${pct}%` }} />
      </div>
      <p className="mt-1.5 flex justify-between text-[0.6875rem] font-semibold text-ink-700">
        <span>
          의견 {card.answered}/{card.required}
        </span>
        <span className={card.ready ? 'text-[var(--good-text)]' : 'text-[var(--warn-text)]'}>{card.ready ? '✓ 완료' : `${short}명 더 필요`}</span>
      </p>
    </button>
  )
}

/** 구성원이 나 혼자일 때(Figma '준비 전 (방장 흐름)') — 추천은 여럿의 의견이 있어야 열린다. 친구를 부르게 한다. */
export function SoloBody({ mapId }: { mapId: string }) {
  const readiness = useReadinessQuery(mapId)
  const { share, url } = useShareInvite(mapId)
  const cards = readiness.data ? toReadinessCards(readiness.data) : []
  return (
    <div className="space-y-3">
      <ul className="divide-y divide-ink-200 rounded-xl border border-brand-300 bg-brand-50 px-3 text-sm">
        {cards.map((c) => (
          <li key={c.category} className="flex justify-between py-2">
            <span className="font-bold text-ink-900">{c.category}</span>
            <span className="text-xs text-ink-500">{c.answered ? `의견 ${c.answered}/${c.required}` : '의견 없음'}</span>
          </li>
        ))}
      </ul>
      <p className="text-xs text-ink-500">지금은 나 혼자예요. 친구를 초대해서 핀에 ♥ △ <AgainstMark />를 남겨 보세요</p>
      <button
        type="button"
        onClick={() => void share()}
        disabled={!url}
        className="flex w-full items-center justify-center gap-2 rounded-xl bg-brand-600 py-3.5 font-bold text-white disabled:opacity-50"
      >
        <Share size={18} aria-hidden="true" /> 초대 링크 공유하기
      </button>
    </div>
  )
}
