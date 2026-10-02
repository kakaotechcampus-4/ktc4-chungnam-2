import TabSheet from '@/features/shell/TabSheet'

export default function RecommendTab() {
  return (
    <TabSheet tab="recommend" header={<h2 className="text-xl font-bold text-ink-900">AI 추천</h2>}>
      {/* 준비 판정·근거 확인·결과와 지도에 올리기가 여기로 들어온다(#295). */}
      <p className="text-sm text-ink-500">추천 준비 판정과 대안 핀이 여기에 들어옵니다</p>
    </TabSheet>
  )
}
