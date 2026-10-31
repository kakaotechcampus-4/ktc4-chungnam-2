import { useState, type ReactNode } from 'react'

import type { RecommendCategory } from '@/features/recommend/model'

import { useRunAgentAction } from './actions'
import type { AgentSummaryDto } from './model'

/** 추천 대상 카테고리(api-spec RecommendCategory). 그 밖의 카테고리 요약엔 추천 버튼이 없다. */
const RECOMMENDABLE: string[] = ['음식점', '카페', '관광지'] satisfies RecommendCategory[]

/**
 * 우리 조건 요약(agent-v2 8절, 16.2 3번). 카테고리 탭 + 다섯 칸. 칸 나누기와 개수는 서버 코드가 한다 — 이름 없이 개수만.
 * 비어 있는 칸은 그리지 않는다. 「이 조건으로 ○○ 추천 받기」는 제안이 아니라 accept 없이 바로 추천을 시작한다.
 */
export default function SummarySection({ mapId, summaries, onDone }: { mapId: string; summaries: AgentSummaryDto[]; onDone: () => void }) {
  const [picked, setPicked] = useState<string | null>(null)
  const runAction = useRunAgentAction(mapId)
  const summary = summaries.find((s) => s.category === picked) ?? summaries[0]
  if (!summary) return null

  return (
    <section className="space-y-3 border-t border-ink-100 pt-4">
      <h3 className="text-sm font-bold text-ink-900">우리 조건 요약</h3>
      {summaries.length > 1 && (
        <div role="group" aria-label="카테고리" className="flex flex-wrap gap-2">
          {summaries.map((s) => (
            <button key={s.category} type="button" aria-pressed={s.category === summary.category} onClick={() => setPicked(s.category)} className="chip">
              {s.category}
            </button>
          ))}
        </div>
      )}
      <Box title="지키려는 조건" items={summary.must_keep.map((i) => `${i.label} · ${i.member_count}명`)} />
      <Box title="겹치는 선호" items={summary.common_prefs.map((i) => `${i.label} · ${i.member_count}명`)} />
      <Box title="갈리는 선호" items={summary.split_prefs.map((i) => `${i.label} · 원함 ${i.want_count} / 피함 ${i.avoid_count}`)} />
      {summary.vague_fixable.count > 0 && <Box title={`더 적어 주면 반영돼요 · ${summary.vague_fixable.count}건`} items={summary.vague_fixable.requests} />}
      {summary.not_filtered.count > 0 && <Box title={`추천이 거르지 않아요 · ${summary.not_filtered.count}건`} items={summary.not_filtered.notices} />}
      {RECOMMENDABLE.includes(summary.category) && (
        <button
          type="button"
          onClick={() => {
            onDone()
            runAction({ index: 0, type: 'open_recommend', label: '', params: { category: summary.category } })
          }}
          className="btn-outline btn-md w-full"
        >
          이 조건으로 {summary.category} 추천 받기
        </button>
      )}
    </section>
  )
}

function Box({ title, items }: { title: string; items: ReactNode[] }) {
  if (items.length === 0) return null
  return (
    <div className="space-y-1 rounded-xl px-3 py-2.5 ring-1 ring-ink-200">
      <p className="text-xs font-bold text-ink-600">{title}</p>
      <ul className="space-y-0.5 text-body text-ink-900">
        {items.map((item, i) => (
          <li key={i} className="break-keep">
            {item}
          </li>
        ))}
      </ul>
    </div>
  )
}
