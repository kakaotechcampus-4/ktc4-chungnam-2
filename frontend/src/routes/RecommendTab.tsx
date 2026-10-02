import { useMapQuery } from '@/features/maps/queries'
import { useAiStore } from '@/features/recommend/aiStore'
import EvidenceScreen from '@/features/recommend/EvidenceScreen'
import { AiHeader, ReadinessBody, SoloBody } from '@/features/recommend/Readiness'
import { useShell } from '@/features/shell/shellContext'
import TabSheet from '@/features/shell/TabSheet'

/**
 * AI 추천 탭(Figma 6절). run 의 상태가 화면을 정한다.
 * 없음 → 준비 판정 · 근거 모으는 중/지역 확인 대기 → 근거 확인 · 실행 중 → 진행 · 끝 → 결과
 * AI는 지도를 바꾸지 않는다 — 여기서 찾은 대안은 나에게만 보이고 「지도에 올리기」로만 공개된다(가드레일 1).
 */
export default function RecommendTab() {
  const { mapId } = useShell()
  const run = useAiStore((s) => s.runs[mapId])
  const memberCount = useMapQuery(mapId).data?.memberCount

  if (run && (run.status === 'collecting_evidence' || run.status === 'awaiting_region_confirm')) {
    return <EvidenceScreen mapId={mapId} run={run} />
  }

  if (run) {
    // 진행·결과 화면은 다음 PR(#295 ②)에서 붙인다.
    return (
      <TabSheet tab="recommend" header={<AiHeader title={`${run.category} 대안을 찾고 있어요`} sub="화면을 닫아도 계속 찾아요" />}>
        <p className="text-sm text-ink-500">결과 화면을 준비하고 있어요</p>
      </TabSheet>
    )
  }

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
