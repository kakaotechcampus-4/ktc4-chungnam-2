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
import FieldError from '@/ui/FieldError'
import Mark from '@/ui/Mark'
import RangeSlider from '@/ui/RangeSlider'
import Sentences from '@/ui/Sentences'

import { useAiStore } from './aiStore'
import {
  chosenCategory,
  radiusKm,
  kmInputToM,
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
        <p className="flex items-start gap-1.5 font-bold text-ink-900">
          <span className="tag tag-ai mt-px shrink-0">AI</span>
          <span className="min-w-0">
            <Sentences text={title} />
          </span>
        </p>
        {sub && (
          <p className="text-xs text-ink-600">
            <Sentences text={sub} />
          </p>
        )}
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
            {current && <span className="ml-auto text-xs text-link">진행 중</span>}
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
  const chosenReadiness = chosen ? readiness.data?.[chosen] : undefined
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
  // 캐시에 남은 예전 준비 상태로 고르지 않는다 — 처음 열 때 다시 받는 중이면 끝난 값을 기다린다(#1583).
  useAgentStart(readiness.isFetching ? [] : cards, (category) => {
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
      {/* 카테고리는 같은 폭으로 한 줄에 둔다 — 개수가 홀수라고 한 칸만 커지지 않게. */}
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${cards.length}, minmax(0, 1fr))` }}>
        {cards.map((c) => (
          <ReadinessTile key={c.category} card={c} selected={c.category === chosen} onPick={() => setPicked(mapId, c.category)} />
        ))}
      </div>
      {radiusM && chosenReadiness?.radius_min_m && chosenReadiness.radius_max_m && (
        <RadiusPicker
          min={chosenReadiness.radius_min_m}
          max={chosenReadiness.radius_max_m}
          defaultM={chosenReadiness.radius_m}
          marks={radiusOptions(chosenReadiness)}
          value={radiusM}
          // 끄는 동안 지도 원이 따라온다. 근처 정예 수(「주변에 추천할 장소가 없어요」)는 손을 뗄 때 한 번 다시 센다.
          onChange={(m) => setRadius(mapId, m)}
          onCommit={(m) => {
            setRadius(mapId, m)
            void readiness.refetch()
          }}
        />
      )}
      <p className="text-label text-ink-500">
        <Sentences text="지도 가운데 원 안에서 추천해요. 다른 지역은 지도를 움직여 보세요." />
      </p>
      {/* 카테고리마다 의견 핀이 몇 곳 필요한지는 타일(「N곳 더 필요」)이 보여 준다.
          사유가 곧 추천 조건이 된다(②) — 의견이 많을수록 거르고 고를 근거가 늘어난다. */}
      <p className="text-label text-ink-500"><Sentences text="구성원의 의견이 모일수록 모두가 만족할 만한 장소를 찾을 수 있어요." /></p>
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

/** 슬라이더 한 칸(m)과 눈금에 붙는 거리(m) — 화면이 고르는 단위다. 하한·상한·기본값은 서버 값이다(#1416). */
const RADIUS_STEP_M = 100
const RADIUS_SNAP_M = 150

/**
 * 「찾는 범위」 — 추천 원의 반경(#1416). 슬라이더는 1km 눈금 근처에서 붙고, 정확한 값은 오른쪽 칸에 km로 넣는다(소수 첫째 자리).
 * 고를 수 있는 범위와 처음 값은 서버가 준다(Readiness.radius_min_m·max_m·radius_m).
 */
function RadiusPicker({
  min,
  max,
  defaultM,
  marks,
  value,
  onChange,
  onCommit,
}: {
  min: number
  max: number
  /** 서버 기본 반경(Readiness.radius_m). 그 눈금에 「기본」을 단다. */
  defaultM?: number
  marks: number[]
  value: number
  onChange: (m: number) => void
  onCommit: (m: number) => void
}) {
  const labelId = useId()
  const errorId = useId()
  // 쓰는 중인 글자. null 이면 칸이 닫혀 있고 고른 값을 글자로 보인다 — 입력칸(16px, 아이폰 확대 방지)은 누를 때만 연다.
  const [typing, setTyping] = useState<string | null>(null)
  const [error, setError] = useState(false)
  function commitTyped() {
    if (typing === null) return
    const m = kmInputToM(typing, min, max, RADIUS_STEP_M)
    if (m === null) return setError(true)
    setError(false)
    setTyping(null)
    onCommit(m)
  }
  return (
    <div className="space-y-1">
      <div className="flex min-h-11 items-center justify-between gap-2">
        <span id={labelId} className="text-sm font-bold text-ink-900">
          찾는 범위
        </span>
        {typing === null ? (
          <button
            type="button"
            onClick={() => setTyping(String(value / 1000))}
            aria-label={`찾는 범위 직접 넣기, 지금 ${radiusKm(value)}`}
            className="hit-44 text-sm font-bold text-selected underline decoration-dotted underline-offset-4"
          >
            {radiusKm(value)}
          </button>
        ) : (
          <span className="field min-h-10 w-28 px-3">
            <input
              autoFocus
              type="number"
              inputMode="decimal"
              step={RADIUS_STEP_M / 1000}
              min={min / 1000}
              max={max / 1000}
              value={typing}
              onChange={(e) => setTyping(e.target.value)}
              onBlur={commitTyped}
              onKeyDown={(e) => {
                if (e.key === 'Escape') {
                  setTyping(null)
                  setError(false)
                }
                if (e.key !== 'Enter') return
                e.preventDefault() // 준비 화면의 폼 제출(추천받기)로 번지지 않게
                commitTyped()
              }}
              aria-labelledby={labelId}
              aria-invalid={error}
              aria-describedby={error ? errorId : undefined}
              // 브라우저 기본 위아래 화살표는 숨긴다 — 값은 슬라이더와 글자로 바꾼다.
              className="w-full min-w-0 bg-transparent text-right outline-none [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none"
            />
            <span aria-hidden="true" className="text-sm text-ink-500">
              km
            </span>
          </span>
        )}
      </div>
      <RangeSlider
        min={min}
        max={max}
        step={RADIUS_STEP_M}
        value={value}
        marks={marks}
        snapWithin={RADIUS_SNAP_M}
        format={(m) => (m === defaultM ? `${radiusKm(m)}, 기본` : radiusKm(m))}
        markLabel={(m) => (m === defaultM ? `기본 ${radiusKm(m)}` : radiusKm(m))}
        label="찾는 범위"
        onChange={(m) => {
          setTyping(null)
          setError(false)
          onChange(m)
        }}
        onCommit={onCommit}
      />
      {error && (
        <FieldError id={errorId}>
          {radiusKm(min)}에서 {radiusKm(max)} 사이로 넣어 주세요
        </FieldError>
      )}
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

function ReadinessTile({ card, selected, onPick }: { card: ReadinessCard; selected: boolean; onPick: () => void }) {
  const short = Math.max(0, card.required - card.answered)
  // 이름과 한 줄 상태만 둔다. 고른 칸만 파란 테두리, 준비 안 된 칸은 누를 수 없고 상태를 주의색 글자로 알린다.
  // 센 것은 사람이 아니라 의견이 달린 핀이다(#360).
  return (
    <button
      type="button"
      disabled={!card.ready}
      aria-pressed={selected}
      onClick={onPick}
      className={`press rounded-xl border px-3 py-2.5 text-left disabled:bg-ink-50 ${
        selected ? 'border-brand-600 bg-[var(--selected-bg)] ring-1 ring-brand-600' : 'border-ink-200 bg-surface'
      }`}
    >
      <span className={`block font-bold ${card.ready ? 'text-ink-900' : 'text-ink-500'}`}>{card.category}</span>
      <span className={`mt-0.5 block break-keep text-xs ${card.ready ? 'text-ink-600' : 'text-[var(--warn-text)]'}`}>
        {card.ready ? `의견 핀 ${card.answered}곳` : `${short}곳 더 필요`}
      </span>
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
