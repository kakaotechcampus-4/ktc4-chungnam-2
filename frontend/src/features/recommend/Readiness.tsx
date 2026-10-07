import { useEffect, useState } from 'react'
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

/** 실행 단계(실격 거르기·순위는 코드가 한다 — 가드레일 7). */
const RUN_STEPS = ['반경 안 후보를 모으는 중', '꼭 지켜야 하는 조건으로 거르는 중', '구성원 선호로 순서를 정하는 중']
/** run 만들기 단계 — 사유를 조건으로 정리하는 건 AI(②) 한 번뿐이다(CLAUDE.md 모델 호출). */
const COLLECT_STEPS = ['구성원 의견을 모으는 중', 'AI가 사유를 조건으로 정리하는 중', '확인할 조건을 준비하는 중']
const STEP_MS = 3000

/**
 * 진행 중(Figma '진행 중'). v1 서버는 단계 이벤트(run.progress)를 보내지 않는다 — 실행이 요청 안에서 끝난다
 * (docs/events.md「v1에서 발행하지 않는 이벤트」). 그래서 요청이 돌아올 때까지 정해진 단계를 시간으로 넘긴다.
 * 마지막 단계에서는 멈춰 있는다. 실제 진행과 맞지 않을 수 있어 단계에 숫자·퍼센트는 붙이지 않는다.
 */
export function ProgressBody({ steps = RUN_STEPS }: { steps?: string[] }) {
  const [at, setAt] = useState(0)
  useEffect(() => {
    if (at >= steps.length - 1) return
    const t = setTimeout(() => setAt(at + 1), STEP_MS)
    return () => clearTimeout(t)
  }, [at, steps.length])
  return (
    <ol aria-live="polite" className="space-y-2 rounded-xl border border-brand-300 bg-brand-50 p-3 text-sm">
      {steps.slice(0, at + 1).map((label, i) => {
        const current = i === at
        return (
          <li key={label} className={`flex items-center gap-2 ${current ? 'font-bold text-ink-900' : 'text-ink-700'}`}>
            <span aria-hidden="true" className={current ? 'animate-pulse' : ''}>
              {current ? '●' : '✓'}
            </span>
            {label}
            {current && <span className="ml-auto text-xs text-brand-600">진행 중</span>}
          </li>
        )
      })}
    </ol>
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
      {/* run 을 만들 때 AI가 사유를 조건으로 정리한다(②) — 5~12초 걸린다(백엔드 안내). 그동안 진행을 보인다. */}
      {create.isPending && <ProgressBody steps={COLLECT_STEPS} />}
      {create.error && <ErrorText message={runErrorMessage(create.error)} error={create.error} />}
      <button
        type="button"
        disabled={!chosen || create.isPending}
        onClick={() => chosen && create.mutate(chosen)}
        className="btn-primary w-full py-3.5"
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
        {/* 「4/2」처럼 분자가 분모를 넘으면 뜻이 헷갈려서 두 숫자를 따로 적는다(#344). */}
        <span>
          의견 {card.answered}명 · 필요 {card.required}명
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
      <p className="text-xs text-ink-500">지금은 나 혼자예요. 친구를 초대해서 핀에 ♥ <AgainstMark />를 남겨 보세요</p>
      <button
        type="button"
        onClick={() => void share()}
        disabled={!url}
        className="btn-primary flex w-full items-center justify-center gap-2 py-3.5"
      >
        <Share size={18} aria-hidden="true" /> 초대 링크 공유하기
      </button>
    </div>
  )
}
