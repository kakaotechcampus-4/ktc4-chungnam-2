import { useEffect, useRef, useState } from 'react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import AdArea from '@/features/ads/AdArea'
import { useRecommendAds } from '@/features/ads/queries'
import { useMembersQuery } from '@/features/maps/queries'
import { useAiStore } from '@/features/recommend/aiStore'
import ConditionsCard from '@/features/recommend/ConditionsCard'
import EvidenceScreen from '@/features/recommend/EvidenceScreen'
import { attemptLimit, noResultsApplied, noResultsFunnel, type RecommendRunDto } from '@/features/recommend/model'
import { useExecuteRunMutation, useResultQuery } from '@/features/recommend/queries'
import { AiHeader, ProgressBody, ReadinessBody, ReadinessHeader } from '@/features/recommend/Readiness'
import {
  BackToReadiness,
  Failed,
  HowPicked,
  NoResults,
  ResultsBody,
  ResultsHeader,
  RetryLimit,
} from '@/features/recommend/Results'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'
import { josa } from '@/ui/josa'

/**
 * AI 추천 탭(Figma 6절). run 의 상태가 화면을 정한다.
 * 없음 → 준비 판정 · 실행 중 → 진행 · 끝 → 결과(0곳·실패 포함). 「추천받기」 한 번에 사유 정리와 첫 검색이 끝나서(#845)
 * 근거 확인 화면을 거치지 않는다 — 조건은 결과 위 「이 조건으로 찾았어요」 카드에서 고치고 다시 추천한다.
 * 지역 확인 대기만 결과 전에 묻는다(5-6-1). 예전 방식으로 만들어 첫 실행 전인 run 은 열자마자 실행한다.
 * AI는 지도를 바꾸지 않는다 — 여기서 찾은 대안은 나에게만 보이고 「지도에 올리기」로만 공개된다(가드레일 1).
 */
export default function RecommendTab() {
  const { mapId } = useShell()
  const run = useAiStore((s) => s.runs[mapId])
  // 광고 조회는 탭을 연 동안 한 번이다 — 안의 화면이 바뀌어도(근거 확인처럼 광고가 없는 화면 포함) 여기서 붙잡아 둔다.
  useRecommendAds(mapId)

  if (run?.status === 'awaiting_region_confirm') return <EvidenceScreen mapId={mapId} run={run} />
  if (run?.status === 'collecting_evidence') return <ResumeRun mapId={mapId} run={run} />
  // 다시 추천·반경 넓히기마다 화면(어떻게 골랐나요 등)을 처음부터 그린다.
  if (run) return <RunResult key={`${run.id}-${run.attempt_no}-${run.default_radius_walk_min ?? 0}`} mapId={mapId} run={run} />

  // 혼자 쓰는 지도도 같은 조건으로 추천을 받는다(2026-10-07, #360) — 구성원 수로 막지 않는다.
  return (
    <TabSheet tab="recommend" header={<ReadinessHeader mapId={mapId} />}>
      <div className="pb-[100px]">
        <ReadinessBody mapId={mapId} />
        <AdArea mapId={mapId} />
      </div>
    </TabSheet>
  )
}

/** 첫 실행 전인 run(예전 방식으로 만들었거나 첫 실행 전에 멈춘 것) — 근거 확인 없이 바로 실행한다(#849 폴백). */
function ResumeRun({ mapId, run }: { mapId: string; run: RecommendRunDto }) {
  const execute = useExecuteRunMutation(mapId)
  // 한 번만 보낸다(개발 모드는 효과가 두 번 돈다). 보내는 순간 run 이 '실행 중'이 되어 이 화면은 사라진다.
  const sent = useRef(false)
  useEffect(() => {
    if (sent.current) return
    sent.current = true
    execute.mutate(run)
  }, [execute, run])
  return (
    <TabSheet tab="recommend" header={<AiHeader title={`${run.category} 대안을 찾고 있어요`} sub="화면을 닫아도 계속 찾아요" mood="thinking" />}>
      <ProgressBody />
    </TabSheet>
  )
}

type View = { kind: 'list' } | { kind: 'how' } | { kind: 'limit' }

function RunResult({ mapId, run }: { mapId: string; run: RecommendRunDto }) {
  const result = useResultQuery(run)
  const members = useMembersQuery(mapId).data ?? []
  const [view, setView] = useState<View>({ kind: 'list' })
  // 「이 조건으로 찾았어요」 카드 펼침 — 0곳 화면의 「조건 고치기」·조언의 근거 버튼도 이걸 연다.
  const [conditionsOpen, setConditionsOpen] = useState(false)
  const back = () => setView({ kind: 'list' })

  const noResults = noResultsFunnel(result.error)
  const failed = run.status === 'failed' || (result.error instanceof ApiError && result.error.code === 'RECOMMEND_FAILED')
  const tab = (header: React.ReactNode, body: React.ReactNode) => (
    <TabSheet tab="recommend" header={header}>
      {/* 광고는 추천 전·진행·결과·0곳·실패 모두에서 맨 아래에 따로 놓인다(docs/ads.md 4절). */}
      <div className="pb-[100px]">
        {body}
        <AdArea mapId={mapId} hide={result.data?.candidates} />
      </div>
    </TabSheet>
  )
  const conditions = (applied: ReturnType<typeof noResultsApplied>) => (
    <ConditionsCard run={run} applied={applied.lines} noApplied={applied.none} open={conditionsOpen} onOpenChange={setConditionsOpen} />
  )

  // 실행 중이면 다른 무엇보다 먼저 '진행 중'이다 — 같은 시도의 예전 결과(0곳·실패)가 캐시에 남아 있어도 덮는다(#349).
  if (run.status === 'executing') {
    return tab(<AiHeader title={`${run.category} 대안을 찾고 있어요`} sub="화면을 닫아도 계속 찾아요" mood="thinking" />, <ProgressBody />)
  }
  if (view.kind === 'limit') {
    return tab(
      <>
        <BackToReadiness mapId={mapId} />
        {/* 상한은 사람마다, 카테고리와 상관없이 센다(#31). */}
        <AiHeader title={`추천은 ${attemptLimit(run)}번까지만 받을 수 있어요`} sub={`이 지도에서 추천을 ${attemptLimit(run)}번 모두 받았어요`} />
      </>,
      <RetryLimit onBack={back} />,
    )
  }
  if (failed) {
    return tab(
      <>
        <BackToReadiness mapId={mapId} />
        <AiHeader title="추천을 끝내지 못했어요" sub="조건이 까다로워서가 아니에요. 잠깐 문제가 생겼어요" mood="error" />
      </>,
      <Failed mapId={mapId} run={run} />,
    )
  }
  if (noResults) {
    return tab(
      <>
        <BackToReadiness mapId={mapId} />
        <AiHeader title={`조건에 맞는 ${run.category}${josa(run.category, '을', '를')} 찾지 못했어요`} sub="조건이 까다로워서가 아니라, 반경 안에 맞는 곳이 없었어요" mood="sorry" />
      </>,
      <NoResults
        mapId={mapId}
        run={run}
        error={result.error}
        onFixEvidence={() => setConditionsOpen(true)}
        conditions={conditions(noResultsApplied(result.error))}
      />,
    )
  }
  if (!result.data) {
    return tab(
      <AiHeader title={`${run.category} 대안을 찾고 있어요`} sub="화면을 닫아도 계속 찾아요" mood="thinking" />,
      result.error ? <ErrorText message="결과를 불러오지 못했어요" error={result.error} /> : <ProgressBody />,
    )
  }

  const data = result.data
  const count = data.candidates.length
  if (view.kind === 'how') {
    return tab(<AiHeader title="어떻게 골랐나요" sub="조건은 코드가 거르고, 순위도 규칙대로 정해요" />, <HowPicked funnel={data.funnel} count={count} onBack={back} />)
  }
  // 머리글의 수는 이번 실행이 새로 찾은 곳이다(new_count, 올려도 줄지 않는다) — 이미 올린 곳은 목록 아래에 따로 보인다(#849).
  const found = data.new_count ?? data.candidates.filter((c) => c.visibility !== 'published').length
  return tab(
    <ResultsHeader mapId={mapId} run={run} count={found} onLimit={() => setView({ kind: 'limit' })} />,
    <ResultsBody
      mapId={mapId}
      run={run}
      result={data}
      members={members}
      onHow={() => setView({ kind: 'how' })}
      conditions={conditions({ lines: data.applied_evidence, none: data.no_applied_conditions })}
      onOpenConditions={() => setConditionsOpen(true)}
    />,
  )
}
