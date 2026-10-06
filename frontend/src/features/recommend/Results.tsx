import { useState } from 'react'
import { MessageSquare, RotateCw, Users } from 'lucide-react'

import { ApiError } from '@/api'
import type { MemberView } from '@/features/maps/model'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'

import { useAiStore } from './aiStore'
import {
  fulfillmentLine,
  noResultsFunnel,
  RETRY_MAX,
  toChecks,
  type CandidateDto,
  type FunnelRow,
  type RecommendResultDto,
  type RecommendRunDto,
} from './model'
import { useExecuteRunMutation, usePublishMutation, useRetryMutation, useWidenMutation } from './queries'
import { AiHeader } from './Readiness'

const TONE = {
  pass: 'bg-[var(--good-bg)] text-[var(--good-text)]',
  check: 'bg-[var(--warn-bg)] text-[var(--warn-text)]',
  fail: 'bg-[var(--bad-bg)] text-[var(--bad-text)]',
} as const
const MARK = { pass: '✓', check: '?', fail: '✗' } as const

const PROVIDER: Record<string, string> = { kakao: '카카오맵', naver: '네이버지도', google: '구글맵', permit: '인허가 공공데이터', tourapi: '한국관광공사' }

/** 시트 안 이전 화면(Figma '‹ AI 추천'). 결과에서 빠져나와 준비 판정으로 돌아간다. */
export function BackToReadiness({ mapId }: { mapId: string }) {
  const setRun = useAiStore((s) => s.setRun)
  return (
    <button type="button" onClick={() => setRun(mapId, undefined)} className="hit-44 mb-2 text-[0.8125rem] font-medium text-ink-500">
      ‹ AI 추천
    </button>
  )
}

/** 결과 머리글 — "관광지 대안 3곳을 찾았어요" + 「↻ 다시 추천 · N번 남음」. */
export function ResultsHeader({ mapId, run, count, onLimit }: { mapId: string; run: RecommendRunDto; count: number; onLimit: () => void }) {
  const retry = useRetryMutation(mapId)
  const left = Math.max(0, RETRY_MAX - run.attempt_no)
  return (
    <div>
      <BackToReadiness mapId={mapId} />
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <AiHeader title={`${run.category} 대안 ${count}곳을 찾았어요`} sub="나에게만 보여요 · 올린 곳만 모두에게 보여요" />
        </div>
        <button
          type="button"
          disabled={retry.isPending}
          onClick={() =>
            // 남은 횟수가 없으면 보내지 않고 상한 화면으로(서버도 429 로 막는다). 그 밖의 결과는 요청 훅이 처리한다(#349).
            left === 0 ? onLimit() : retry.mutate(run)
          }
          className="shrink-0 text-right text-xs font-bold text-brand-600 disabled:opacity-50"
        >
          <span className="flex items-center gap-1">
            <RotateCw size={12} aria-hidden="true" /> 다시 추천
          </span>
          <span className="font-normal text-ink-500">{retry.isPending ? '찾는 중…' : `${left}번 남음`}</span>
        </button>
      </div>
    </div>
  )
}

/** 결과 목록(Figma 'AI 결과 탭'). 카드마다 이유·조건별 체크·구성원 충족·출처가 붙는다(가드레일 5). */
export function ResultsBody({
  mapId,
  run,
  result,
  members,
  onOpen,
  onHow,
}: {
  mapId: string
  run: RecommendRunDto
  result: RecommendResultDto
  members: MemberView[]
  onOpen: (candidateId: string) => void
  onHow: () => void
}) {
  const removed = result.funnel.reduce((sum, f) => sum + f.removed_count, 0)
  return (
    <div className="space-y-3">
      <button type="button" onClick={onHow} className="flex w-full justify-between rounded-lg bg-ink-50 px-3 py-2 text-xs text-ink-700">
        <span>
          조건으로 {removed}곳 걸러냄 → 추천 {result.candidates.length}곳
        </span>
        <span className="font-bold text-brand-600">어떻게 골랐나요 ›</span>
      </button>
      <ol className="space-y-3 pb-[100px]">
        {result.candidates.map((c) => (
          <li key={c.id}>
            <CandidateCard mapId={mapId} run={run} c={c} members={members} onOpen={() => onOpen(c.id)} />
          </li>
        ))}
      </ol>
    </div>
  )
}

function CandidateCard({ mapId, run, c, members, onOpen }: { mapId: string; run: RecommendRunDto; c: CandidateDto; members: MemberView[]; onOpen: () => void }) {
  return (
    <article className="space-y-2 rounded-2xl border-[1.5px] border-brand-300 bg-brand-50 p-3.5">
      <header className="flex items-center gap-2">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-full border-2 border-[var(--bad-line)] text-xs font-bold text-[var(--bad-line)]">
          {c.rank}
        </span>
        <h3 className="min-w-0 flex-1 truncate text-lg font-bold text-ink-900">{c.place_name}</h3>
        {c.region_label && <span className="shrink-0 rounded-md border border-brand-300 bg-white px-1.5 text-[0.6875rem] text-brand-700">{c.region_label} 기준</span>}
      </header>
      <p className="text-xs text-ink-500">{run.category}</p>
      <Reason text={c.reason} />
      <Checks c={c} />
      <p className="flex items-center gap-1.5 text-xs font-bold text-brand-700">
        <Users size={14} aria-hidden="true" /> {c.member_fulfillment.total}명 중 {c.member_fulfillment.satisfied}명 조건 충족
        <span className="ml-auto font-normal text-ink-500">출처 · {PROVIDER[c.place_source?.provider ?? ''] ?? '확인 안 됨'}</span>
      </p>
      <div className="flex items-center justify-between">
        <PublishButton mapId={mapId} run={run} c={c} />
        <button type="button" onClick={onOpen} className="text-xs text-ink-500">
          자세히 ›
        </button>
      </div>
      <span className="sr-only">{fulfillmentLine(c, members)}</span>
    </article>
  )
}

function Reason({ text }: { text: string }) {
  return (
    <p className="flex gap-2 rounded-lg border border-brand-300 bg-white p-2.5 text-[0.8125rem] text-ink-900">
      <MessageSquare size={14} className="mt-0.5 shrink-0 text-ink-500" aria-hidden="true" />
      {text}
    </p>
  )
}

function Checks({ c }: { c: CandidateDto }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {toChecks(c).map((k) => (
        <li key={k.label} className={`rounded-md px-2 py-0.5 text-xs font-semibold ${TONE[k.tone]}`}>
          {MARK[k.tone]} {k.label}
          {k.tone === 'check' && ' (확인 필요)'}
        </li>
      ))}
    </ul>
  )
}

/** 목록에선 외곽선, 상세에선 그 화면의 유일한 채움 버튼. 올린 뒤에는 "모두에게 보여요"로 바뀐다. */
function PublishButton({ mapId, run, c, filled = false }: { mapId: string; run: RecommendRunDto; c: CandidateDto; filled?: boolean }) {
  const publish = usePublishMutation(mapId, run)
  if (c.visibility === 'published') {
    return <span className="rounded-lg bg-[var(--good-bg)] px-3 py-1.5 text-xs font-bold text-[var(--good-text)]">✓ 지도에 올렸어요 · 모두에게 보여요</span>
  }
  if (!c.permissions.can_publish) return null
  return (
    <button
      type="button"
      disabled={publish.isPending}
      onClick={() =>
        publish.mutate(c.id, {
          onSuccess: () => {
            const name = c.place_name ?? '이 장소'
            showToast(`${name}${josa(name, '을', '를')} 지도에 올렸어요. 이제 모든 구성원이 봐요`)
          },
          onError: (err) =>
            showToast(err instanceof ApiError && err.code === 'PIN_DUPLICATE' ? '이미 지도에 있는 장소예요' : '지도에 올리지 못했어요'),
        })
      }
      className={
        filled
          ? 'w-full rounded-xl bg-brand-600 py-3.5 font-bold text-white disabled:opacity-50'
          : 'rounded-lg border-[1.5px] border-brand-600 bg-white px-3 py-1.5 text-sm font-bold text-brand-600 disabled:opacity-50'
      }
    >
      {publish.isPending ? '올리는 중…' : '지도에 올리기'}
    </button>
  )
}

/** 후보 상세(Figma '후보 상세'). */
export function CandidateDetail({
  mapId,
  run,
  c,
  count,
  members,
  onBack,
}: {
  mapId: string
  run: RecommendRunDto
  c: CandidateDto
  count: number
  members: MemberView[]
  onBack: () => void
}) {
  return (
    <div className="space-y-3">
      <div className="flex justify-between text-[0.8125rem]">
        <button type="button" onClick={onBack} className="font-medium text-ink-500">
          ‹ 추천 결과 {count}곳
        </button>
        <span className="text-ink-500">{c.visibility === 'published' ? '모두에게 보여요' : '나에게만 보여요'}</span>
      </div>
      <div>
        <h3 className="text-[1.375rem] font-bold text-ink-900">{c.place_name}</h3>
        <p className="text-[0.8125rem] text-ink-600">
          {run.category}
          {c.region_label && ` · ${c.region_label} 기준`} · {c.rank}순위
        </p>
      </div>
      <Reason text={c.reason} />
      <section>
        <h4 className="mb-1 text-sm font-bold text-ink-900">조건별 충족</h4>
        <ul className="space-y-0.5 text-[0.8125rem]">
          {toChecks(c).map((k) => (
            <li key={k.label} className={k.tone === 'pass' ? 'text-[var(--good-text)]' : k.tone === 'check' ? 'text-[var(--warn-text)]' : 'text-[var(--bad-text)]'}>
              {MARK[k.tone]} {k.label}
              {k.tone === 'check' && ' — 정보가 없어 확인이 필요해요'}
            </li>
          ))}
        </ul>
      </section>
      <section>
        <h4 className="text-sm font-bold text-ink-900">
          구성원 충족 {c.member_fulfillment.total}명 중 {c.member_fulfillment.satisfied}명
        </h4>
        <p className="text-[0.8125rem] text-ink-600">{fulfillmentLine(c, members)}</p>
      </section>
      <p className="text-[0.6875rem] text-ink-500">
        출처 · {PROVIDER[c.place_source?.provider ?? ''] ?? '확인 안 됨'}
        {c.place_source?.url && (
          <>
            {' · '}
            <a href={c.place_source.url} target="_blank" rel="noopener noreferrer" className="underline">
              장소 정보 보기
            </a>
          </>
        )}
      </p>
      <PublishButton mapId={mapId} run={run} c={c} filled />
    </div>
  )
}

/** 어떻게 골랐나요(Figma) — 깔때기 + 순위 규칙. 조건은 코드가 거르고 순위도 코드가 정한다(가드레일 7, #99). */
export function HowPicked({ funnel, count, onBack }: { funnel: FunnelRow[]; count: number; onBack: () => void }) {
  return (
    <div className="space-y-3">
      <button type="button" onClick={onBack} className="hit-44 text-[0.8125rem] font-medium text-ink-500">
        ‹ 추천 결과 {count}곳
      </button>
      <h3 className="text-xl font-bold text-ink-900">이렇게 {count}곳을 골랐어요</h3>
      <FunnelTable funnel={funnel} left={count} />
      <section className="text-[0.8125rem] text-ink-600">
        <h4 className="mb-1 font-bold text-ink-900">순위는 이렇게 정했어요</h4>
        <ul className="list-inside list-disc space-y-0.5">
          <li>가능하면 맞춰 달라는 조건에 맞는 개수로 점수를 매겼어요</li>
          <li>지역마다 1위를 먼저 뽑고 남은 자리를 채웠어요</li>
          <li>조건은 코드가 거르고, 순위도 규칙대로 계산했어요</li>
        </ul>
      </section>
    </div>
  )
}

function FunnelTable({ funnel, left }: { funnel: FunnelRow[]; left: number }) {
  return (
    <table className="w-full rounded-xl bg-brand-50 text-[0.8125rem]">
      <tbody>
        {funnel.map((f) => (
          <tr key={f.label} className="border-b border-brand-100">
            <td className="px-3 py-1.5 text-ink-700">{f.label}</td>
            <td className="px-3 py-1.5 text-right font-semibold text-ink-900">{f.removed_count ? `−${f.removed_count}곳` : ''}</td>
          </tr>
        ))}
        <tr>
          <td className="px-3 py-1.5 font-bold text-brand-700">남은 곳</td>
          <td className={`px-3 py-1.5 text-right font-bold ${left ? 'text-brand-700' : 'text-[var(--warn-text)]'}`}>{left}곳</td>
        </tr>
      </tbody>
    </table>
  )
}

/**
 * 결과 0곳(Figma '결과 0곳'). 0곳은 0곳으로 보여준다(가드레일 2) — 무엇을 시도했는지 깔때기로 남긴다(가드레일 10).
 * 반경을 넓히는 건 사람이다(가드레일 4): 기본값 원만 넓히고, 사람이 쓴 반경은 그대로 둔다고 먼저 묻는다.
 */
export function NoResults({ mapId, run, error, onFixEvidence }: { mapId: string; run: RecommendRunDto; error: unknown; onFixEvidence: () => void }) {
  const widen = useWidenMutation(mapId)
  const [asking, setAsking] = useState(false)
  const funnel = noResultsFunnel(error) ?? []
  const now = run.default_radius_walk_min ?? 15

  return (
    <div className="space-y-3">
      <FunnelTable funnel={funnel} left={0} />
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={() => setAsking(true)} disabled={widen.isPending} className="rounded-xl bg-brand-600 py-3 font-bold text-white disabled:opacity-50">
          반경 넓히기
        </button>
        <button type="button" onClick={onFixEvidence} className="rounded-xl border border-brand-600 py-3 font-semibold text-brand-600">
          근거 고치기
        </button>
      </div>
      <button type="button" onClick={() => document.getElementById('place-search')?.focus()} className="text-sm font-semibold text-brand-600">
        직접 찍기 — 검색창에서 찾아보기
      </button>

      {asking && (
        <div role="alertdialog" aria-modal="true" aria-label="반경 넓히기 확인" className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-6">
          <div className="w-full max-w-sm space-y-2 rounded-2xl bg-white p-5">
            <p className="text-lg font-bold text-ink-900">기본 반경만 넓혀서 다시 찾을까요?</p>
            <dl className="space-y-1 rounded-lg bg-ink-50 p-3 text-sm">
              <div className="flex gap-2">
                <dt className="text-ink-500">넓혀요</dt>
                <dd className="font-semibold text-ink-900">
                  핀 주변 기본 반경 (도보 {now}분 → {now + 5}분)
                </dd>
              </div>
              <div className="flex gap-2">
                <dt className="text-ink-500">그대로예요</dt>
                <dd className="font-semibold text-ink-900">사람이 직접 정한 반경 조건</dd>
              </div>
            </dl>
            <p className="text-sm text-ink-600">사람이 직접 정한 반경은 넓히지 않아요. 더 멀리 찾고 싶으면 그 사유를 고쳐 주세요.</p>
            <p className="text-xs text-ink-500">꼭 지켜야 하는 조건도 그대로 적용돼요.</p>
            <div className="grid grid-cols-2 gap-2 pt-2">
              <button type="button" onClick={() => setAsking(false)} className="rounded-lg border border-ink-300 py-2.5 text-sm font-semibold">
                취소
              </button>
              <button
                type="button"
                onClick={() =>
                  // 진행 중 → 결과/실패/상한 안내는 요청 훅이 맡는다(#349).
                  widen.mutate(run, { onSettled: () => setAsking(false) })
                }
                disabled={widen.isPending}
                className="rounded-lg bg-brand-600 py-2.5 text-sm font-bold text-white disabled:opacity-50"
              >
                {widen.isPending ? '다시 찾는 중…' : '넓혀서 다시 찾기'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/** 추천 실패(Figma '추천 실패'). 조건 탓이 아니다 — 남긴 것은 그대로 있고, 다시 시도는 횟수에서 빠지지 않는다. */
export function Failed({ mapId, run }: { mapId: string; run: RecommendRunDto }) {
  const execute = useExecuteRunMutation(mapId)
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-brand-300 bg-brand-50 p-3 text-sm">
        <p className="font-bold text-brand-700">남긴 의견과 근거는 그대로 있어요</p>
        <p className="text-xs text-ink-600">이번 시도는 다시 추천 횟수에서 빠지지 않아요</p>
      </div>
      <button
        type="button"
        disabled={execute.isPending}
        // 다시 '진행 중'으로 간다. 또 실패하면 이 화면으로, 다른 오류는 토스트로(요청 훅, #349).
        onClick={() => execute.mutate(run)}
        className="w-full rounded-xl border-[1.5px] border-brand-600 py-3 font-bold text-brand-600 disabled:opacity-50"
      >
        {execute.isPending ? '다시 찾는 중…' : '다시 시도'}
      </button>
    </div>
  )
}

/** 다시 추천 상한(Figma '다시 추천 상한', RETRY_LIMIT). */
export function RetryLimit({ onBack }: { onBack: () => void }) {
  return (
    <div className="space-y-3">
      <ul className="list-inside list-disc space-y-1 rounded-xl border border-brand-300 bg-brand-50 p-3 text-sm text-ink-700">
        <li>지금 떠 있는 후보 중 괜찮은 곳을 지도에 올려 보세요</li>
        <li>근거를 고치면 다른 결과가 나올 수 있어요</li>
        <li>검색창에서 직접 찾아 찍을 수도 있어요</li>
      </ul>
      <div className="grid grid-cols-2 gap-2">
        <button type="button" onClick={onBack} className="rounded-xl border border-brand-600 py-3 font-semibold text-brand-600">
          후보 다시 보기
        </button>
        <button type="button" onClick={() => document.getElementById('place-search')?.focus()} className="rounded-xl border border-brand-600 py-3 font-semibold text-brand-600">
          직접 찍기
        </button>
      </div>
    </div>
  )
}
