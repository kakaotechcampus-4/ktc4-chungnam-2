import { useEffect, useId, useRef, useState } from 'react'
import { useOutletContext, useSearchParams } from 'react-router'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import { timeAgo } from '@/features/map/model'
import { circleOutsideRegion, useRegionBoundary } from '@/features/map/regionGeo'
import { useMapQuery } from '@/features/maps/queries'
import { CHANGED, START_PARAM } from '@/features/agent/actions'
import { useSheetStore } from '@/features/shell/sheetStore'
import type { ShellContext } from '@/features/shell/shellContext'
import { showToast } from '@/features/shell/toast'
import ConfirmDialog from '@/ui/ConfirmDialog'
import Notice from '@/ui/Notice'
import Pingo, { type PingoMood } from '@/ui/Pingo'
import PingoLoading from '@/ui/PingoLoading'
import ExternalSearchLink from '@/ui/ExternalSearchLink'

import CreditConfirm from '@/features/credits/CreditConfirm'
import CreditGate from '@/features/credits/CreditGate'
import { creditBlock } from '@/features/credits/model'
import { useCreditsQuery } from '@/features/credits/queries'
import Mark from '@/ui/Mark'

import { useAiStore } from './aiStore'
import {
  chosenCategory,
  radiusKm,
  radiusOptions,
  readinessRadiusM,
  recommendAreaNote,
  runErrorMessage,
  runHistoryLine,
  summaryToRun,
  toReadinessCards,
  type ReadinessCard,
  type RecommendCategory,
} from './model'
import { useCreateRunMutation, useReadinessQuery, useRunHistoryQuery } from './queries'

/** AI 탭 시트 머리글 — 핑고 + 「AI」 배지. 표정은 그 화면의 상황을 따른다(Pingo.tsx). */
export function AiHeader({ title, sub, mood }: { title: string; sub?: string; mood?: PingoMood }) {
  return (
    <div className="flex items-center gap-3 rounded-xl bg-[var(--pingo-bg)] p-3">
      <Pingo size={44} mood={mood} />
      <div className="min-w-0">
        <p className="flex items-center gap-1.5 font-bold text-ink-900">
          <span className="tag tag-ai">AI</span>
          {title}
        </p>
        {sub && <p className="text-xs text-ink-600">{sub}</p>}
      </div>
    </div>
  )
}

/** 준비 판정 머리글. 추천받을 수 있는 카테고리가 하나도 없으면 핑고가 「의견이 부족해요」로 알린다(시안 ALERT). */
export function ReadinessHeader({ mapId }: { mapId: string }) {
  const readiness = useReadinessQuery(mapId)
  const short = readiness.data !== undefined && !toReadinessCards(readiness.data).some((c) => c.ready)
  return short ? (
    <AiHeader title="의견이 부족해요" sub="핀에 좋음 또는 반대 의견을 남겨 주시면 AI가 추천을 준비해요" mood="alert" />
  ) : (
    <AiHeader title="AI 추천" sub="추천받을 카테고리를 골라 주세요" mood="welcome" />
  )
}

/** 다시 추천·반경 넓히기 단계 — 모델 없이 코드만 돈다(실격 거르기·순위는 코드가 한다 — 가드레일 7). */
const RUN_STEPS = ['반경 안 후보를 모으는 중', '꼭 지켜야 하는 조건으로 거르는 중', '구성원 선호로 순서를 정하는 중']
/** 「추천받기」 단계 — 사유를 조건으로 정리(AI ②, 한 번뿐)하고 곧바로 찾는다(#845). */
const START_STEPS = ['AI가 의견을 조건으로 정리하는 중', '조건에 맞는 곳을 찾는 중', '구성원 선호로 순서를 정하는 중']
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
    <ol aria-live="polite" className="space-y-2 rounded-xl border border-brand-300 bg-[var(--pingo-bg)] p-3 text-sm">
      {steps.slice(0, at + 1).map((label, i) => {
        const current = i === at
        return (
          <li key={label} className={`flex items-center gap-2 ${current ? 'font-bold text-ink-900' : 'text-ink-700'}`}>
            <span aria-hidden="true" className={`flex w-3.5 justify-center ${current ? 'animate-pulse' : ''}`}>
              {current ? <span className="size-2 rounded-full bg-current" /> : <Mark kind="check" size={14} />}
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
  const picked = useAiStore((s) => s.picked[mapId])
  const setPicked = useAiStore((s) => s.setPicked)
  const chosen = chosenCategory(cards, picked)
  // 찾는 범위는 「찾는 범위」에서 고른 반경, 안 골랐으면 고른 카테고리의 서버 기본값이다(#1416, #1468). 지도 원(MapLayout)도 같은 값을 본다.
  const pickedRadius = useAiStore((s) => s.radius[mapId])
  const setRadius = useAiStore((s) => s.setRadius)
  const radiusM = readinessRadiusM(readiness.data, chosen, pickedRadius)
  const radiusChoices = radiusOptions(chosen ? readiness.data?.[chosen] : undefined)
  const search = cards.find((c) => c.category === chosen)?.externalSearch
  useRecountOnMapMove(readiness.refetch)
  // 크레딧을 쓰기 전에 묻는다(쓸 크레딧·남은 크레딧·찾는 범위). 버튼과 핑고 조언의 「추천 받아 보기」가 같은 창을 거친다.
  const [asking, setAsking] = useState<{ category: RecommendCategory; fromAgent: boolean } | null>(null)
  // 추천 원이 통째로 여행 지역 밖이면 크레딧 창 대신 지역으로 돌아가라고 안내한다(그 지역 이름).
  const [away, setAway] = useState<string | null>(null)
  const outside = useOutsideRegion(mapId, radiusM)
  const showRegion = useOutletContext<ShellContext | null>()?.showRegion
  function ask(category: RecommendCategory, fromAgent: boolean) {
    const region = outside()
    if (region) setAway(region)
    else setAsking({ category, fromAgent })
  }
  // 게스트는 묻지 않는다 — 버튼 자리에 이미 카카오 안내가 있고, 실행해도 403 이다.
  const guest = creditBlock(useCreditsQuery().error)?.kind === 'guest'
  useAgentStart(cards, (category) => {
    setPicked(mapId, category)
    if (!guest) ask(category, true)
  })
  function startAsked() {
    if (!asking) return
    setAsking(null)
    // 핑고 조언에서 왔으면 준비가 풀린 것(NOT_READY)만 「상황이 바뀌었어요」다. 크레딧·실패·네트워크는 버튼 자리의 안내가 진짜 이유를 말한다.
    const changed = (err: Error) => err instanceof ApiError && err.code === 'NOT_READY' && showToast(CHANGED)
    // 사람이 반경을 골랐을 때만 보낸다 — 안 보내면 서버 기본값이다.
    create.start(asking.category, { onError: asking.fromAgent ? changed : undefined, radiusM: pickedRadius ? radiusM : null })
  }

  if (readiness.isPending) return <PingoLoading label="준비 상태를 확인하는 중…" />
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
            onPick={() => setPicked(mapId, c.category)}
          />
        ))}
      </div>
      {radiusM && radiusChoices.length > 1 && (
        <RadiusPicker
          options={radiusChoices}
          value={radiusM}
          onPick={(m) => {
            setRadius(mapId, m)
            // 근처 정예 수(「주변에 추천할 장소가 없어요」)를 고른 반경으로 다시 센다.
            void readiness.refetch()
          }}
        />
      )}
      <p className="text-label text-ink-500">지도 가운데 원 안에서 추천해요. 다른 지역은 지도를 움직여 보세요.</p>
      {/* 카테고리마다 의견 핀이 몇 곳 필요한지는 타일(「N곳 더 필요」)이 보여 준다.
          사유가 곧 추천 조건이 된다(②) — 의견이 많을수록 거르고 고를 근거가 늘어난다. */}
      <p className="text-label text-ink-500">구성원의 의견이 모일수록 모두가 만족할 만한 장소를 찾을 수 있어요.</p>
      {/* 사유 정리(②)와 첫 검색을 한 요청에서 끝낸다(#845) — 몇 초 걸린다. 그동안 진행을 보인다. */}
      {create.isPending && <ProgressBody steps={START_STEPS} />}
      {/* 실패하면 run 이 생기지 않고 크레딧도 쓰지 않는다 — 같은 버튼을 다시 누르면 새 시도다. 크레딧 오류는 CreditGate 가 보인다. */}
      {create.error && !creditBlock(create.error) && <ErrorText message={runErrorMessage(create.error)} error={create.error} />}
      {/* 보고 있는 곳 근처에 정예 장소가 없으면 추천해도 0곳이다 — 막지 않고 밖에서 찾는 길을 같이 둔다(#798, #1331). */}
      {search && (
        <Notice action={<ExternalSearchLink search={search} className="btn-outline btn-sm" />}>보고 있는 곳 주변에는 아직 추천할 장소가 없어요</Notice>
      )}
      <CreditGate feature="recommend_run" mapId={mapId} error={create.error} onCharged={create.reset}>
        <button
          type="button"
          disabled={!chosen || create.isPending}
          onClick={() => chosen && ask(chosen, false)}
          className="btn-primary btn-lg w-full"
        >
          {create.isPending ? '추천을 찾는 중…' : chosen ? `${chosen} 추천받기` : '의견이 모이면 추천받을 수 있어요'}
        </button>
      </CreditGate>
      {asking && (
        <CreditConfirm
          feature="recommend_run"
          title={`${asking.category} 추천을 받을까요?`}
          ok="추천받기"
          note={recommendAreaNote(radiusM)}
          onOk={startAsked}
          onCancel={() => setAsking(null)}
        />
      )}
      {away && (
        <ConfirmDialog
          title="여행 지역 밖이에요"
          body={`${away}로 돌아가서 추천받아 주세요`}
          cancel="닫기"
          ok="여행 지역으로 가기"
          onOk={() => {
            setAway(null)
            showRegion?.()
          }}
          onCancel={() => setAway(null)}
        />
      )}
      <RunHistory mapId={mapId} />
    </div>
  )
}

/**
 * 「찾는 범위」 — 추천 원의 반경을 고르는 칩 줄(#1416). 고를 수 있는 값과 처음 값은 서버가 준다(Readiness.radius_min_m·max_m·radius_m).
 * 고르면 지도 원이 바로 바뀌고, 「추천받기」가 그 반경으로 찾는다.
 */
function RadiusPicker({ options, value, onPick }: { options: number[]; value: number; onPick: (m: number) => void }) {
  const labelId = useId()
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span id={labelId} className="text-label text-ink-500">
        찾는 범위
      </span>
      <div role="group" aria-labelledby={labelId} className="flex flex-wrap gap-2">
        {options.map((m) => (
          <button key={m} type="button" aria-pressed={m === value} onClick={() => onPick(m)} className="chip">
            {radiusKm(m)}
          </button>
        ))}
      </div>
    </div>
  )
}

/**
 * 추천 원(보이는 지도 가운데 반경 radiusM)이 통째로 여행 지역 밖이면 그 지역 이름, 아니면 null(누를 때 본다).
 * 원이 경계에 걸치기만 해도 막지 않는다. 지역을 고르지 않은 지도, 경계를 아직 못 받은 지도, 서버 반경이 없는 응답도 막지 않는다.
 * 지금은 화면만 보는 규칙이다 — 서버가 지역 밖 오류를 내리면 그 응답으로 바꾼다(#1385).
 */
function useOutsideRegion(mapId: string, radiusM: number | null) {
  const getCenter = useOutletContext<ShellContext | null>()?.getCenter
  const region = useMapQuery(mapId).data?.region?.label
  const boundary = useRegionBoundary(region)
  return () => {
    const at = getCenter?.() ?? null
    return region && boundary && at && radiusM && circleOutsideRegion(at, radiusM, boundary) ? region : null
  }
}

/**
 * 「근처 정예 수」는 보이는 지도 가운데로 센다(#1331). 지도를 끌어 옮기고 멈추면 다시 센다.
 * mapMoving 은 끌기를 시작할 때 켜지고 멈추면(idle) 꺼진다 — 꺼지는 순간이 다시 셀 때다.
 */
function useRecountOnMapMove(recount: () => unknown) {
  const moving = useSheetStore((s) => s.mapMoving)
  const moved = useRef(false)
  useEffect(() => {
    if (moving) moved.current = true
    else if (moved.current) {
      moved.current = false
      void recount()
    }
  }, [moving, recount])
}

/**
 * 「핑고 AI 조언」 버튼(open_recommend)으로 들어오면 주소의 카테고리로 손으로 누를 때와 같은 추천을 한 번 시작한다(agent-v2 16.3).
 * 그새 준비가 풀렸으면 시작하지 않고 「상황이 바뀌었어요」.
 */
function useAgentStart(cards: ReadinessCard[], start: (category: RecommendCategory) => void) {
  const [params, setParams] = useSearchParams()
  const wanted = params.get(START_PARAM)
  // 한 번만 시작한다 — cards·start 는 렌더마다 새로 만들어져 효과가 자주 돌고, 개발 모드(StrictMode)는 두 번 돈다.
  const started = useRef<string | null>(null)
  const ready = cards.length > 0
  useEffect(() => {
    if (!wanted || !ready || started.current === wanted) return
    started.current = wanted
    setParams(
      (p) => {
        p.delete(START_PARAM)
        return p
      },
      { replace: true },
    )
    const card = cards.find((c) => c.category === wanted)
    if (card?.ready) start(card.category)
    else showToast(CHANGED)
  }, [wanted, ready, cards, setParams, start])
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
      className={`press rounded-xl border-[1.5px] p-3 text-left ${wide ? 'col-span-2' : ''} ${
        selected ? 'border-brand-600 bg-[var(--selected-bg)]' : card.ready ? 'border-[var(--good-line)] bg-white' : 'border-[var(--warn-line)] bg-white'
      }`}
    >
      <p className="flex items-start justify-between gap-1 font-bold text-ink-900">
        {/* 상태는 태그 하나에 담는다. 흰 글자 + 주의 선 색(3.5:1)은 작은 글자 기준(4.5:1)에 못 미쳐서 바탕·글자 세트로 칠한다. */}
        <span className="flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-1">
          {card.category}
          <span className={`tag ${card.ready ? 'tag-good' : 'tag-warn'}`}>{card.ready ? '준비 완료' : `${short}곳 더 필요`}</span>
        </span>
        {selected && (
          <span role="img" aria-label="선택됨" className="text-brand-600">
            <Mark kind="check" size={16} />
          </span>
        )}
      </p>
      <div className="mt-2 h-1.5 rounded-full bg-ink-200">
        <div className={`h-full rounded-full ${card.ready ? 'bg-[var(--good-line)]' : 'bg-[var(--warn-line)]'}`} style={{ width: `${pct}%` }} />
      </div>
      {/* 센 것은 사람이 아니라 의견이 달린 핀이다(#360). 「4/1」처럼 분자가 분모를 넘으면 뜻이 헷갈려서 두 숫자를 따로 적는다(#344). */}
      {/* 360px 폭(태블릿 패널·작은 휴대폰)에서 줄이 어색하게 끊기지 않게 낱말 단위로 바꾼다(#603). 상태는 위 태그에 있다. */}
      <p className="mt-1.5 break-keep text-label font-semibold text-ink-700">
        의견 핀 {card.answered}곳 · <span className="whitespace-nowrap">필요 {card.required}곳</span>
      </p>
    </button>
  )
}

/**
 * 지난 추천(#482) — 내가 이 지도에서 받은 추천만, 최근순. 누르면 그 결과를 다시 연다(크레딧을 쓰지 않는다).
 * 없으면 아무것도 그리지 않는다. 못 받으면 조용히 넘기지 않고 한 줄 알린다.
 */
const HISTORY_SHOWN = 5

function RunHistory({ mapId }: { mapId: string }) {
  const history = useRunHistoryQuery(mapId)
  const setRun = useAiStore((s) => s.setRun)
  const [all, setAll] = useState(false)
  if (history.error) return <ErrorText message="지난 추천을 불러오지 못했어요" error={history.error} />
  const runs = history.data ?? []
  if (runs.length === 0) return null
  const shown = all ? runs : runs.slice(0, HISTORY_SHOWN)

  return (
    <section aria-labelledby="run-history" className="pt-3">
      <h3 id="run-history" className="mb-1 text-sm font-bold text-ink-900">
        지난 추천
      </h3>
      <ul className="-mx-4 divide-y divide-ink-100">
        {shown.map((r) => (
          <li key={r.id}>
            <button type="button" onClick={() => setRun(mapId, summaryToRun(r))} className="flex w-full items-center gap-2 px-4 py-3 text-left hover:bg-ink-50">
              <span className="min-w-0 flex-1">
                <span className="block text-body font-semibold text-ink-900">{r.category} 추천</span>
                <span className="mt-0.5 block text-xs text-ink-500">
                  {runHistoryLine(r)} · {timeAgo(r.created_at)}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
      {!all && runs.length > HISTORY_SHOWN && (
        <button type="button" onClick={() => setAll(true)} className="btn-text mt-1 w-full text-center text-body">
          지난 추천 {runs.length - HISTORY_SHOWN}개 더 보기
        </button>
      )}
    </section>
  )
}
