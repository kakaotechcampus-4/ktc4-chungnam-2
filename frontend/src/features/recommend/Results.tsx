import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { RotateCw, TriangleAlert } from 'lucide-react'

import { ApiError } from '@/api'
import RunAdvice from '@/features/agent/RunAdvice'
import CreditBox from '@/features/credits/CreditBox'
import type { MemberView } from '@/features/maps/model'
import PanelBackLink from '@/features/shell/PanelBackLink'
import { showToast } from '@/features/shell/toast'
import { goToPlaceSearch } from '@/features/search/goToPlaceSearch'
import { useCreditsQuery } from '@/features/credits/queries'
import ConfirmDialog from '@/ui/ConfirmDialog'
import { josa } from '@/ui/josa'
import Notice from '@/ui/Notice'
import SheetTitle from '@/ui/SheetTitle'
import ExternalSearchLink from '@/ui/ExternalSearchLink'
import Sentences from '@/ui/Sentences'
import BusyLabel from '@/ui/BusyLabel'
import MapAppLinks from '@/ui/MapAppLinks'

import { useAiStore } from './aiStore'
import { AiChecks, AiFulfillment, AiReason } from './Evidence'
import {
  hasExcluded,
  missingWants,
  noResultsExternalSearch,
  noResultsFunnel,
  sourceLabel,
  type CandidateDto,
  type FunnelRow,
  type RecommendResultDto,
  type RecommendRunDto,
  WIDEN_LIMIT_MESSAGE,
  widenAtLimit,
  widenLine,
} from './model'
import { useEvidencePatching, useEvidenceQuery, useExecuteRunMutation, usePublishMutation, useRetryMutation, useWidenMutation } from './queries'
import { AiHeader } from './Readiness'

/** 시트 안 이전 화면(Figma '‹ AI 추천'). 결과에서 빠져나와 준비 판정으로 돌아간다. 넓은 화면은 패널 헤더 ‹ 다. */
export function BackToReadiness({ mapId }: { mapId: string }) {
  const setRun = useAiStore((s) => s.setRun)
  return <PanelBackLink label="AI 추천" onBack={() => setRun(mapId, undefined)} />
}

/**
 * 결과 머리글 — "관광지 대안 3곳을 찾았어요" + 둘째 줄 "509곳을 거르고 3곳을 골랐어요 어떻게 골랐나요"(#1706, 예전엔 목록 위 따로 한 줄),
 * 그 아래 "다시 추천"과 오른쪽 크레딧 칸(CreditBox, "크레딧 안 써요"). count 는 이번 실행이 새로 찾은 곳(new_count)이다.
 * 결과가 처음 뜰 때 핑고의 하트가 한 번 떠오른다(#1706). 목록에서 상세를 보고 돌아올 때는 다시 뜨지 않는다(shownRuns).
 */
export function ResultsHeader({ mapId, run, count, removed, onHow }: { mapId: string; run: RecommendRunDto; count: number; removed?: number; onHow?: () => void }) {
  const [celebrate] = useState(() => !shownRuns.has(run.id))
  const credits = useCreditsQuery().data
  return (
    <div>
      <BackToReadiness mapId={mapId} />
      <AiHeader title={count ? `${run.category} 대안 ${count}곳을 찾았어요` : '이번엔 새로 찾은 곳이 없어요'} mood={count ? 'heart' : 'sad'} celebrate={celebrate && count > 0}>
        {removed !== undefined && onHow && (
          <p className="flex flex-wrap items-center gap-x-1.5 text-xs text-ink-600">
            {removed}곳을 거르고 {count}곳을 골랐어요
            <button type="button" onClick={onHow} className="btn-link text-xs">
              어떻게 골랐나요
            </button>
          </p>
        )}
      </AiHeader>
      <div className="mt-2 flex gap-2">
        <RetryButton mapId={mapId} run={run} className="btn-outline btn-md flex-1" />
        {/* 숫자는 GET /credits/me 그대로(#733). 못 받으면 비운다 — 다시 추천은 크레딧과 무관하게 된다. */}
        {credits && <CreditBox cost={0} credits={credits} />}
      </div>
    </div>
  )
}

/**
 * 다시 추천 — 고친 조건으로, 지금 후보를 빼고 찾는다(#845). 크레딧을 쓰지 않고 횟수 상한도 없다(#432 D5) — 그래서 확인 창 없이 바로 간다.
 * 머리(외곽선)와 목록 끝(채움, #1706) 두 자리에 있다. 카드를 다 보고 마음에 드는 곳이 없을 때가 누르는 때라 목록 끝이 주 자리다.
 * 조건을 고치는 요청이 끝나기 전에는 막는다 — 고친 게 빠진 채 찾지 않게. 결과(실패 포함)는 요청 훅이 처리한다(#349).
 */
function RetryButton({ mapId, run, className, label = '다시 추천' }: { mapId: string; run: RecommendRunDto; className: string; label?: string }) {
  const retry = useRetryMutation(mapId)
  const patching = useEvidencePatching(run.id)
  const busy = retry.isPending ? '찾는 중…' : patching ? '조건 반영 중…' : null
  return (
    <button type="button" disabled={!!busy} aria-busy={!!busy} onClick={() => retry.mutate(run)} className={className}>
      <BusyLabel busy={!!busy} busyText={busy ?? ''}>
        <RotateCw size={16} aria-hidden="true" /> {label}
      </BusyLabel>
    </button>
  )
}

/** 결과를 이미 보여 준 실행. 후보 상세에서 목록으로 돌아올 때는 다시 나타나지 않게 한다(#595). */
const shownRuns = new Set<string>()

const quoted = (labels: string[]) => labels.map((l) => `‘${l}’`).join(', ')

/**
 * 결과 목록(Figma 'AI 결과 탭'). 카드마다 이유·조건별 체크·구성원 충족·출처가 붙는다(가드레일 5).
 * 맨 위는 「이 조건으로 찾았어요」 카드(conditions). 이번에 새로 찾은 곳과 이미 지도에 올린 곳을 나눠 보인다 —
 * 다시 추천은 올린 곳을 남기고 나머지를 바꾸기 때문이다(#845). 새로 찾은 곳이 없으면 그렇게 말하고 넓히기·밖에서 찾기를 둔다.
 */
export function ResultsBody({
  mapId,
  run,
  result,
  members,
  conditions,
  onOpenConditions,
}: {
  mapId: string
  run: RecommendRunDto
  result: RecommendResultDto
  members: MemberView[]
  conditions?: ReactNode
  onOpenConditions?: () => void
}) {
  const fresh = result.candidates.filter((c) => c.visibility !== 'published')
  const published = result.candidates.filter((c) => c.visibility === 'published')
  // 「이번 검색 0건」과 「찾은 곳을 다 올려서 남은 게 없음」을 가른다 — new_count 는 올려도 줄지 않는다(구버전 서버면 남은 수로).
  const noneFound = (result.new_count ?? fresh.length) === 0
  const missing = missingWants(result.candidates, useEvidenceQuery(run.id).data ?? [])
  const [enter] = useState(() => !shownRuns.has(run.id))
  useEffect(() => {
    shownRuns.add(run.id)
  }, [run.id])
  return (
    <div className={`space-y-3 ${enter ? 'enter-fade' : ''}`}>
      {conditions}
      {/* 알러지는 거르지 않는다 — 데이터로 보장할 수 없어서 사유와 상관없이 항상 안내한다(#425). 올린 곳만 보인다는 말과 한 줄로 둔다(#1706). */}
      <p className="flex items-start gap-1 px-0.5 text-xs text-ink-500">
        <TriangleAlert size={14} className="mt-px shrink-0" aria-hidden="true" />
        <span className="min-w-0">
          <Sentences text="알러지가 있다면 가게에 직접 확인해 주세요. 지도에 올린 곳만 모두에게 보여요" />
        </span>
      </p>
      <RunAdvice mapId={mapId} run={run} widen={<WidenButton mapId={mapId} run={run} className="btn-outline btn-sm" />} onOpenEvidence={onOpenConditions} />
      {/* 원한 조건에 맞는 곳이 반경 안에 없으면 다른 곳만 보여 주지 않고 이유를 말한다. 넓히는 건 사람이다(가드레일 4). */}
      {missing.length > 0 && (
        <Notice action={<WidenButton mapId={mapId} run={run} className="btn-outline btn-sm" />}>
          {hasExcluded(result.funnel)
            ? `현재 검색 반경 내에 ${quoted(missing)} 조건을 만족하는 새로운 장소가 없어요. 반경을 넓혀 볼까요?`
            : `현재 검색 반경에서는 ${quoted(missing)} 조건을 만족하는 곳이 없어 다른 곳을 골랐어요. 반경을 넓혀 볼까요?`}
        </Notice>
      )}
      <div className="space-y-3">
        {fresh.length > 0 && (
          <ol className="space-y-3">
            {fresh.map((c) => (
              <li key={c.id}>
                <CandidateCard mapId={mapId} run={run} c={c} members={members} />
              </li>
            ))}
          </ol>
        )}
        {noneFound && (
          <Notice action={<WidenButton mapId={mapId} run={run} className="btn-outline btn-sm" />}>
            조건을 고치거나 반경을 넓혀 보세요
          </Notice>
        )}
        {/* 후보가 적으면 서버가 링크를 준다(#798). 기준 숫자는 서버가 정한다 — 화면은 링크가 있는지만 본다. */}
        {result.external_search && <ExternalSearchLink search={result.external_search} className="btn-outline btn-md w-full" />}
        {published.length > 0 && (
          <section className="space-y-3 pt-2">
            <h3 className="text-sm font-bold text-ink-900">이미 지도에 올린 곳</h3>
            <ol className="space-y-3">
              {published.map((c) => (
                <li key={c.id}>
                  <CandidateCard mapId={mapId} run={run} c={c} members={members} />
                </li>
              ))}
            </ol>
          </section>
        )}
        {/* 카드를 다 본 자리 — 마음에 드는 곳이 없을 때 누른다(#1706). 이 화면의 채움 버튼은 이것 하나다. */}
        <div className="space-y-1.5 pt-2 text-center">
          <p className="text-body text-ink-600">마음에 드는 곳이 없나요?</p>
          <RetryButton mapId={mapId} run={run} label="다른 곳 다시 추천" className="btn-primary btn-lg w-full" />
          <p className="text-label text-ink-500">크레딧을 쓰지 않아요. 지금 후보를 빼고, 고친 조건으로 찾아요</p>
        </div>
      </div>
    </div>
  )
}

/**
 * 카드를 누르면 지도가 그 후보로 간다(#843). 안의 버튼·링크는 자기 일만 한다. 키보드로는 제목 버튼으로 간다.
 * 지도에서 후보 핑고 핀을 눌러도 같은 후보가 골라지고, 그 카드가 보이게 스크롤한다.
 */
function CandidateCard({ mapId, run, c, members }: { mapId: string; run: RecommendRunDto; c: CandidateDto; members: MemberView[] }) {
  const selected = useAiStore((s) => s.focus?.id === c.id)
  const focusN = useAiStore((s) => (s.focus?.id === c.id ? s.focus.n : 0))
  const focus = () => useAiStore.getState().focusCandidate(c.id)
  const ref = useRef<HTMLElement>(null)
  useEffect(() => {
    if (focusN) ref.current?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [focusN])
  return (
    <article
      ref={ref}
      onClick={(e) => {
        if (!(e.target as HTMLElement).closest('a, button')) focus()
      }}
      className={`press cursor-pointer space-y-2 rounded-xl border-[1.5px] bg-[var(--pingo-bg)] p-3.5 ${selected ? 'border-brand-600' : 'border-brand-300'}`}
    >
      <header className="flex items-center gap-2">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-brand-600 text-xs font-bold text-link">
          {c.rank}
        </span>
        <h3 className="min-w-0 flex-1 text-title font-bold text-ink-900">
          <button
            type="button"
            onClick={focus}
            aria-label={`${c.place_name} 지도에서 보기`}
            aria-current={selected || undefined}
            className="block w-full truncate text-left"
          >
            {c.place_name}
          </button>
        </h3>
      </header>
      {/* 카테고리는 머리("카페 대안")에 있어 카드마다 적지 않는다. 지역 기준과 출처(가드레일 5)를 이름 아래 한 줄로(#1706). */}
      <p className="pl-8 text-xs text-ink-500">
        {[c.region_label && `${c.region_label} 기준`, `출처: ${sourceLabel(c)}`].filter(Boolean).join(', ')}
      </p>
      <AiReason text={c.reason} />
      <AiChecks evidence={c} />
      <AiFulfillment evidence={c} members={members} withSource={false} />
      <div className="flex items-center justify-between">
        <PublishButton mapId={mapId} run={run} c={c} />
        {/* 사진, 주소, 영업시간은 원본 장소 페이지에서 본다. 장소 페이지가 없으면 서버가 이름+동네 검색 링크를 준다(#798). */}
        <MapAppLinks kakao={c.place_url} naver={c.naver_url} variant="inline" />
      </div>
    </article>
  )
}

/** 올린 뒤에는 "모두에게 보여요"로 바뀐다. */
function PublishButton({ mapId, run, c }: { mapId: string; run: RecommendRunDto; c: CandidateDto }) {
  const publish = usePublishMutation(mapId, run)
  // 그사이 누가 같은 곳을 찍었으면(409 PIN_DUPLICATE) 다시 눌러도 같은 오류다 — 광고 칸처럼 버튼을 닫는다.
  const [onMap, setOnMap] = useState(false)
  if (c.visibility === 'published') {
    return <span className="tag tag-good">지도에 올려 모두에게 보여요</span>
  }
  if (!c.permissions.can_publish) return null
  if (onMap) {
    return (
      <button type="button" disabled className="btn-neutral btn-sm">
        이미 지도에 있어요
      </button>
    )
  }
  return (
    <button
      type="button"
      disabled={publish.isPending}
      onClick={() =>
        publish.mutate(c.id, {
          onSuccess: () => {
            const name = c.place_name ?? '이 장소'
            showToast(`${name}${josa(name, '을', '를')} 지도에 올렸어요`)
          },
          onError: (err) => {
            const dup = err instanceof ApiError && err.code === 'PIN_DUPLICATE'
            if (dup) setOnMap(true)
            showToast(dup ? '이미 지도에 있는 장소예요' : '지도에 올리지 못했어요')
          },
        })
      }
      className="btn-outline btn-sm"
    >
      <BusyLabel busy={publish.isPending} busyText="올리는 중…">지도에 올리기</BusyLabel>
    </button>
  )
}

/** 어떻게 골랐나요(Figma) — 깔때기 + 순위 규칙. 조건은 코드가 거르고 순위도 코드가 정한다(가드레일 7, #99). */
export function HowPicked({ funnel, count, onBack }: { funnel: FunnelRow[]; count: number; onBack: () => void }) {
  return (
    <div className="space-y-3">
      <PanelBackLink label={`추천 결과 ${count}곳`} onBack={onBack} />
      <SheetTitle as="h3">이렇게 {count}곳을 골랐어요</SheetTitle>
      <FunnelTable funnel={funnel} left={count} />
      <section className="text-body text-ink-600">
        <h4 className="mb-1 text-sm font-bold text-ink-900">순위는 이렇게 정했어요</h4>
        <ul className="list-inside list-disc space-y-0.5">
          <li><Sentences text="있으면 좋은 조건을 많이 맞출수록 앞에 뒀어요" /></li>
          <li><Sentences text="지역마다 1위를 먼저 뽑고 남은 자리를 채웠어요" /></li>
        </ul>
      </section>
    </div>
  )
}

function FunnelTable({ funnel, left }: { funnel: FunnelRow[]; left: number }) {
  return (
    <table className="w-full rounded-xl bg-[var(--pingo-bg)] text-body">
      <tbody>
        {funnel.map((f) => (
          <tr key={f.label} className="border-b border-brand-100">
            <td className="px-3 py-1.5 text-ink-700">{f.label}</td>
            <td className="px-3 py-1.5 text-right font-semibold text-ink-900">{f.removed_count ? `−${f.removed_count}곳` : ''}</td>
          </tr>
        ))}
        <tr>
          <td className="px-3 py-1.5 font-bold text-selected">남은 곳</td>
          <td className={`px-3 py-1.5 text-right font-bold ${left ? 'text-selected' : 'text-[var(--warn-text)]'}`}>{left}곳</td>
        </tr>
      </tbody>
    </table>
  )
}

/**
 * 결과 0곳(Figma '결과 0곳'). 0곳은 0곳으로 보여준다(가드레일 2) — 무엇을 시도했는지 깔때기로 남긴다(가드레일 10).
 * 반경을 넓히는 건 사람이다(가드레일 4): 기본값 원만 넓히고, 사람이 쓴 반경은 그대로 둔다고 먼저 묻는다.
 */
export function NoResults({
  mapId,
  run,
  error,
  onFixEvidence,
  conditions,
}: {
  mapId: string
  run: RecommendRunDto
  error: unknown
  onFixEvidence: () => void
  conditions?: ReactNode
}) {
  const funnel = noResultsFunnel(error) ?? []
  const search = noResultsExternalSearch(error)
  return (
    <div className="space-y-3">
      {conditions}
      <FunnelTable funnel={funnel} left={0} />
      {/* 아래에 같은 버튼이 있어서 조언은 문장만 보인다. */}
      <RunAdvice mapId={mapId} run={run} />
      <div className="grid grid-cols-2 gap-2">
        <WidenButton mapId={mapId} run={run} className="btn-primary btn-lg" />
        <button type="button" onClick={onFixEvidence} className="btn-outline btn-lg">
          조건 고치기
        </button>
        {/* 핑고 밖에서 찾는 출구(#798). 채움은 「반경 넓히기」 하나라 외곽선이다. */}
        {search && (
          <div className="col-span-2">
            <ExternalSearchLink search={search} className="btn-outline btn-lg w-full" />
          </div>
        )}
      </div>
      <button type="button" onClick={goToPlaceSearch} className="btn-link text-sm">
        검색해서 직접 찍기
      </button>
    </div>
  )
}

/**
 * 「반경 넓히기」 — 기본값 원만 넓히고, 사람이 쓴 반경은 그대로 둔다고 먼저 묻는다(가드레일 4).
 * 지금 반경과 넓힌 뒤 반경은 서버 값만 보인다(#1468). 서버가 이미 상한이라고 알려 주면 누르기 전에 끄고 이유를 붙인다(#1370).
 */
function WidenButton({ mapId, run, className }: { mapId: string; run: RecommendRunDto; className: string }) {
  const widen = useWidenMutation(mapId)
  // 조건을 고치는 중에 넓히면 고친 게 빠진 채 찾는다 — 「다시 추천」처럼 막는다.
  const patching = useEvidencePatching(run.id)
  const [asking, setAsking] = useState(false)
  const limitId = useId()
  if (widenAtLimit(run))
    return (
      <span className="flex flex-col gap-1">
        <button type="button" disabled aria-describedby={limitId} className={className}>
          반경 넓히기
        </button>
        <span id={limitId} className="text-label text-ink-500">
          {WIDEN_LIMIT_MESSAGE}
        </span>
      </span>
    )
  return (
    <>
      <button type="button" onClick={() => setAsking(true)} disabled={widen.isPending || patching} className={className}>
        반경 넓히기
      </button>
      {asking && (
        <ConfirmDialog
          title="기본 반경만 넓혀서 다시 찾을까요?"
          detail={
            <dl className="space-y-1">
              <div className="flex gap-2">
                <dt className="text-ink-500">넓혀요</dt>
                <dd className="font-semibold text-ink-900">{widenLine(run)}</dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-ink-500">그대로예요</dt>
                <dd className="font-semibold text-ink-900">구성원이 직접 정한 반경 조건</dd>
              </div>
            </dl>
          }
          body="직접 정한 반경을 넓히려면 그 사유를 고쳐 주세요."
          note="꼭 지켜야 하는 조건도 그대로 적용돼요."
          ok={widen.isPending ? '다시 찾는 중…' : '넓혀서 다시 찾기'}
          pending={widen.isPending}
          onCancel={() => setAsking(false)}
          onOk={() =>
            // 진행 중 → 결과/실패 안내는 요청 훅이 맡는다(#349).
            widen.mutate(run, { onSettled: () => setAsking(false) })
          }
        />
      )}
    </>
  )
}

/** 추천 실패(Figma '추천 실패'). 조건 탓이 아니다 — 남긴 의견과 조건은 그대로 있고, 같은 버튼으로 다시 시도한다. */
export function Failed({ mapId, run }: { mapId: string; run: RecommendRunDto }) {
  const execute = useExecuteRunMutation(mapId)
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-brand-300 bg-[var(--pingo-bg)] p-3 text-sm">
        <p className="font-bold text-selected">남긴 의견과 조건은 그대로 있어요</p>
        <p className="text-xs text-ink-600">잠시 후 다시 시도해 주세요</p>
      </div>
      <button
        aria-busy={execute.isPending}
        type="button"
        disabled={execute.isPending}
        // 다시 '진행 중'으로 간다. 또 실패하면 이 화면으로, 다른 오류는 토스트로(요청 훅, #349).
        onClick={() => execute.mutate(run)}
        className="btn-outline btn-lg w-full"
      >
        <BusyLabel busy={execute.isPending} busyText="다시 찾는 중…">다시 시도</BusyLabel>
      </button>
    </div>
  )
}
