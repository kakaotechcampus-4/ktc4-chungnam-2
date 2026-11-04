import { Check, CircleCheck, Eye, Flag } from 'lucide-react'

import { timeAgo } from '@/features/map/model'

import { elapsedLabel, triedInOrder, type AgentTrackingDto, type AgentTriedDto } from './model'

/** 상태마다 아이콘과 색 — 글자(서버 문구)가 뜻을 담고, 아이콘은 한눈에 가르는 보조다. 이름은 스크린리더용. */
const STATUS: Record<AgentTrackingDto['status'], { icon: typeof Eye; color: string; label: string }> = {
  watching: { icon: Eye, color: 'text-brand-600', label: '지켜보는 중' },
  resolved: { icon: CircleCheck, color: 'text-[var(--good-text)]', label: '풀림' },
  declared: { icon: Flag, color: 'text-ink-500', label: '해 본 것을 남김' },
}

/**
 * 「지켜보는 중」 — 수락한 제안 뒤로 핑고가 지켜보는 막힌 곳(#1345, agent-v2 6.9). 문구는 서버 고정 문구 그대로이고,
 * 지켜본 시간은 since 로 화면이 따로 그린다(「2시간째」, 문구에 숫자를 붙이지 않는다). 풀림·충돌 선언은 그때가 언제인지만.
 * 없거나 빈 목록이면 자리를 두지 않는다.
 */
export function TrackingList({ tracking }: { tracking?: AgentTrackingDto[] }) {
  if (!tracking?.length) return null
  return (
    <section aria-labelledby="agent-tracking" className="space-y-1.5">
      <h3 id="agent-tracking" className="text-sm font-bold text-ink-900">
        핑고가 지켜보는 곳
      </h3>
      <ul className="space-y-1">
        {tracking.map((t) => {
          const { icon: Icon, color, label } = STATUS[t.status] ?? STATUS.watching
          return (
            <li key={t.suggestion_id} className="flex items-start gap-1.5 text-body text-ink-900">
              <Icon size={14} className={`mt-[3px] shrink-0 ${color}`} aria-label={label} role="img" />
              <span className="min-w-0 break-keep">
                {t.text}
                <span className="ml-1 text-xs text-ink-500">{t.status === 'watching' ? elapsedLabel(t.since) : timeAgo(t.since)}</span>
              </span>
            </li>
          )
        })}
      </ul>
    </section>
  )
}

/** 이 막힌 곳에서 이미 해 본 것(수락한 앞 제안의 버튼, 오래된 것부터). 누가 눌렀는지·추천 결과는 싣지 않는다(#1345). */
export function TriedList({ tried }: { tried?: AgentTriedDto[] }) {
  const items = triedInOrder(tried)
  if (items.length === 0) return null
  return (
    <section aria-labelledby="agent-tried" className="space-y-1.5">
      <h3 id="agent-tried" className="text-sm font-bold text-ink-900">
        해 본 것
      </h3>
      <ol className="space-y-1">
        {items.map((t, i) => (
          <li key={i} className="flex items-start gap-1.5 text-body text-ink-900">
            <Check size={14} className="mt-[3px] shrink-0 text-ink-500" aria-hidden="true" />
            <span className="min-w-0 break-keep">
              {t.label}
              <span className="ml-1 text-xs text-ink-500">{timeAgo(t.accepted_at)}</span>
            </span>
          </li>
        ))}
      </ol>
    </section>
  )
}
