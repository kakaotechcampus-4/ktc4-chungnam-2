import type { AgentMapStatusDto } from './model'

/**
 * 지도 현황 문단(agent-v2 8.2, 16.2 1번). 코드가 계산한 칸을 모델이 보고 쓴 2~4문장이라 「AI」 배지를 붙인다.
 * 서버가 모순·칸 밖 숫자·금지 표현을 걸러 통과한 문단만 내리므로 화면은 고치거나 자르지 않고 그대로 보인다.
 * 없으면(아직 만든 적 없음, 서버가 칸을 안 보냄) 자리를 두지 않는다.
 */
export default function MapStatus({ status }: { status: AgentMapStatusDto | null | undefined }) {
  if (!status) return null
  return (
    <section aria-label="지금 지도 현황" className="space-y-1.5 rounded-xl border-[1.5px] border-brand-300 bg-brand-50 p-3">
      <h3 className="flex items-center gap-1.5 text-sm font-bold text-ink-900">
        <span className="tag tag-ai">AI</span>
        지금 지도 현황
      </h3>
      <p className="break-keep text-body text-ink-900">{status.paragraph}</p>
    </section>
  )
}
