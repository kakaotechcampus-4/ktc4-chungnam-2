import TabSheet from '@/features/shell/TabSheet'

export default function ShortlistTab() {
  return (
    <TabSheet tab="shortlist" header={<h2 className="text-xl font-bold text-ink-900">확정된 장소</h2>}>
      {/* 확정 리스트·동선 보기(순서만)가 여기로 들어온다(#294). */}
      <p className="text-sm text-ink-500">확정한 곳이 여기에 모입니다</p>
    </TabSheet>
  )
}
