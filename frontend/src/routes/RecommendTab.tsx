import { useState } from 'react'

import { ApiError } from '@/api'
import ErrorText from '@/ErrorText'
import { useMapQuery, useMembersQuery } from '@/features/maps/queries'
import { useAiStore } from '@/features/recommend/aiStore'
import EvidenceScreen from '@/features/recommend/EvidenceScreen'
import { noResultsFunnel, RETRY_MAX, type RecommendRunDto } from '@/features/recommend/model'
import { useResultQuery } from '@/features/recommend/queries'
import { AiHeader, ProgressBody, ReadinessBody, SoloBody } from '@/features/recommend/Readiness'
import {
  BackToReadiness,
  CandidateDetail,
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
 * 없음 → 준비 판정 · 근거 모으는 중/지역 확인 대기 → 근거 확인 · 실행 중 → 진행 · 끝 → 결과(0곳·실패 포함)
 * AI는 지도를 바꾸지 않는다 — 여기서 찾은 대안은 나에게만 보이고 「지도에 올리기」로만 공개된다(가드레일 1).
 */
export default function RecommendTab() {
  const { mapId } = useShell()
  const run = useAiStore((s) => s.runs[mapId])
  const memberCount = useMapQuery(mapId).data?.memberCount

  if (run && (run.status === 'collecting_evidence' || run.status === 'awaiting_region_confirm')) {
    return <EvidenceScreen mapId={mapId} run={run} />
  }
  // 다시 추천·반경 넓히기마다 화면(후보 상세 등)을 처음부터 그린다.
  if (run) return <RunResult key={`${run.id}-${run.attempt_no}-${run.default_radius_walk_min ?? 0}`} mapId={mapId} run={run} />

  if (memberCount === 1) {
    return (
      <TabSheet tab="recommend" header={<AiHeader title="의견이 모여야 추천이 열려요" sub="한 카테고리에 의견이 모이면 추천을 받을 수 있어요" />}>
        <SoloBody mapId={mapId} />
      </TabSheet>
    )
  }
  return (
    <TabSheet tab="recommend" header={<AiHeader title="AI 추천" sub="준비된 카테고리를 골라 주세요" />}>
      <ReadinessBody mapId={mapId} />
    </TabSheet>
  )
}

type View = { kind: 'list' } | { kind: 'detail'; id: string } | { kind: 'how' } | { kind: 'limit' }

function RunResult({ mapId, run }: { mapId: string; run: RecommendRunDto }) {
  const result = useResultQuery(run)
  const members = useMembersQuery(mapId).data ?? []
  const setRun = useAiStore((s) => s.setRun)
  const [view, setView] = useState<View>({ kind: 'list' })
  const back = () => setView({ kind: 'list' })
  // 근거 고치기 — 같은 run 의 근거 확인으로 돌아간다. 고친 뒤 다시 실행한다.
  const fixEvidence = () => setRun(mapId, { ...run, status: 'collecting_evidence' })

  const noResults = noResultsFunnel(result.error)
  const failed = run.status === 'failed' || (result.error instanceof ApiError && result.error.code === 'RECOMMEND_FAILED')
  const tab = (header: React.ReactNode, body: React.ReactNode) => (
    <TabSheet tab="recommend" header={header}>
      {body}
    </TabSheet>
  )

  // 실행 중이면 다른 무엇보다 먼저 '진행 중'이다 — 같은 시도의 예전 결과(0곳·실패)가 캐시에 남아 있어도 덮는다(#349).
  if (run.status === 'executing') {
    return tab(<AiHeader title={`${run.category} 대안을 찾고 있어요`} sub="화면을 닫아도 계속 찾아요" />, <ProgressBody />)
  }
  if (view.kind === 'limit') {
    return tab(
      <>
        <BackToReadiness mapId={mapId} />
        <AiHeader title={`${run.category}${josa(run.category, '은', '는')} ${RETRY_MAX}번까지만 찾아요`} sub={`이 지도에서 ${run.category} 추천을 ${RETRY_MAX}번 모두 받았어요`} />
      </>,
      <RetryLimit onBack={back} />,
    )
  }
  if (failed) {
    return tab(
      <>
        <BackToReadiness mapId={mapId} />
        <AiHeader title="추천을 끝내지 못했어요" sub="조건이 까다로워서가 아니에요. 잠깐 문제가 생겼어요" />
      </>,
      <Failed mapId={mapId} run={run} />,
    )
  }
  if (noResults) {
    return tab(
      <>
        <BackToReadiness mapId={mapId} />
        <AiHeader title={`조건에 맞는 ${run.category}${josa(run.category, '을', '를')} 찾지 못했어요`} sub="조건이 까다로워서가 아니라, 반경 안에 맞는 곳이 없었어요" />
      </>,
      <NoResults mapId={mapId} run={run} error={result.error} onFixEvidence={fixEvidence} />,
    )
  }
  if (!result.data) {
    return tab(
      <AiHeader title={`${run.category} 대안을 찾고 있어요`} sub="화면을 닫아도 계속 찾아요" />,
      result.error ? <ErrorText message="결과를 불러오지 못했어요" error={result.error} /> : <ProgressBody />,
    )
  }

  const data = result.data
  const count = data.candidates.length
  if (view.kind === 'detail') {
    const c = data.candidates.find((x) => x.id === view.id)
    if (c) return tab(<AiHeader title="후보 상세" sub="나에게만 보여요" />, <CandidateDetail mapId={mapId} run={run} c={c} count={count} members={members} onBack={back} />)
  }
  if (view.kind === 'how') {
    return tab(<AiHeader title="어떻게 골랐나요" sub="조건은 코드가 거르고, 순위도 규칙대로 정해요" />, <HowPicked funnel={data.funnel} count={count} onBack={back} />)
  }
  return tab(
    <ResultsHeader mapId={mapId} run={run} count={count} onLimit={() => setView({ kind: 'limit' })} />,
    <ResultsBody
      mapId={mapId}
      run={run}
      result={data}
      members={members}
      onOpen={(id) => setView({ kind: 'detail', id })}
      onHow={() => setView({ kind: 'how' })}
    />,
  )
}
