import { useEffect, useState } from 'react'

import ErrorText from '@/ErrorText'
import { timeAgo } from '@/features/map/model'
import { useMembersQuery } from '@/features/maps/queries'
import { AiHeader } from '@/features/recommend/Readiness'
import ModalSheet from '@/features/shell/ModalSheet'
import AgainstMark from '@/ui/AgainstMark'
import PingoLoading from '@/ui/PingoLoading'
import SheetTitle from '@/ui/SheetTitle'
import Switch from '@/ui/Switch'
import { StepRow, type WorkStepDto } from '@/ui/WorkStep'

import { useRunAgentAction } from './actions'
import AdviceText from './AdviceText'
import FactLines from './FactLines'
import MapStatus from './MapStatus'
import SummarySection from './SummarySection'
import { TrackingList, TriedList } from './Tracking'
import { attemptOf, CONFLICT_LABEL, splitAdvice, type AgentAnalysisDto, type AgentSuggestionDto } from './model'
import {
  useAcceptSuggestionMutation,
  useAgentQuery,
  useAgentSettingsMutation,
  useDismissSuggestionMutation,
  useViewSuggestionMutation,
} from './queries'

/**
 * 「핑고 AI 조언」 바텀시트(agent-v2 16.2). 위에서부터 모드 스위치 → 살펴본 시각 → 지켜보는 곳 → 지도 현황 문단 → 지금 제안(0개 또는 1개) → 우리 조건 요약.
 * 제안은 지도 단위라 구성원 모두에게 같다. 에이전트는 아무것도 직접 하지 않고, 버튼은 사람이 하던 동작의 지름길이다.
 */
export default function AgentSheet({ mapId, onClose }: { mapId: string; onClose: () => void }) {
  const query = useAgentQuery(mapId)
  const state = query.data
  const settings = useAgentSettingsMutation(mapId)
  const view = useViewSuggestionMutation(mapId)
  const suggestionId = state?.active_suggestion?.id
  const unseen = state?.has_unseen ?? false
  const members = useMembersQuery(mapId).data ?? []
  const enabled = state?.settings.enabled ?? true
  const changer = members.find((m) => m.userId === state?.settings.updated_by)
  const observation = state?.observation

  // 시트가 열려 있는 동안 제안이 보이면(이벤트로 새로 와도) 열람을 기록하고 점을 끈다.
  const { mutate: markViewed } = view
  useEffect(() => {
    if (suggestionId && unseen) markViewed(suggestionId)
  }, [suggestionId, unseen, markViewed])

  return (
    <ModalSheet label="핑고 AI 조언" onClose={onClose} fullWidth>
      <div className="space-y-4">
        <div className="flex items-center justify-between gap-3">
          <SheetTitle>핑고 AI 조언</SheetTitle>
          {state && (
            <Switch
              checked={enabled}
              onChange={(on) => settings.mutate(on)}
              disabled={settings.isPending}
              label="핑고 AI 조언 켜기"
            />
          )}
        </div>
        {query.isPending && <PingoLoading label="조언을 불러오는 중…" />}
        {query.error && (
          <div className="space-y-2">
            <ErrorText message="조언을 불러오지 못했어요" error={query.error} />
            <button type="button" disabled={query.isFetching} onClick={() => void query.refetch()} className="btn-outline btn-sm">
              다시 시도
            </button>
          </div>
        )}
        {state && !enabled && (
          <p className="text-body text-ink-600">
            {changer ? `${changer.isMe ? '내가' : `${changer.name}님이`} 껐어요` : '꺼져 있어요'}. 켜면 의견이 막힌 곳을 찾아 구성원 모두에게 제안해요
          </p>
        )}
        {state && enabled && observation?.checked_at && <p className="text-xs text-ink-500">{checkedLabel(observation.checked_at)}</p>}
        {state && enabled && <TrackingList tracking={state.tracking} />}
        {state && enabled && <MapStatus status={state.status} />}
        {state && enabled && state.active_suggestion && <Suggestion mapId={mapId} suggestion={state.active_suggestion} onDone={onClose} />}
        {state && enabled && !state.active_suggestion && (
          <div className="space-y-1.5">
            <AiHeader title="지금은 따로 드릴 제안이 없어요" sub="막힌 곳이 보이면 여기에 알려 드릴게요" />
            {/* 제안이 없는 이유 — 서버 고정 문구 그대로(api-spec AgentObservation.notice). 화면은 문구를 적지 않는다. */}
            {observation?.notice && <p className="break-keep text-body text-ink-600">{observation.notice}</p>}
          </div>
        )}
        {state && enabled && <SummarySection mapId={mapId} summaries={state.summaries} onDone={onClose} />}
      </div>
    </ModalSheet>
  )
}

function Suggestion({ mapId, suggestion, onDone }: { mapId: string; suggestion: AgentSuggestionDto; onDone: () => void }) {
  const accept = useAcceptSuggestionMutation(mapId)
  const dismiss = useDismissSuggestionMutation(mapId)
  const runAction = useRunAgentAction(mapId)
  const { facts, guesses } = splitAdvice(suggestion.advice)
  const busy = accept.isPending || dismiss.isPending
  // 같은 막힌 곳의 몇 번째 제안인지(#1345). 다음 방법(1)엔 칩과 해 본 것을 붙인다.
  // 충돌 선언(2)은 버튼이 없고(actions 빈 목록) 서버 문장만 — 그 문장이 해 본 것을 이미 나열해서 목록을 따로 두지 않는다.
  const attempt = attemptOf(suggestion)

  return (
    <article className="space-y-3">
      <AiHeader title={suggestion.title} sub="구성원 모두에게 같은 제안이 보여요" mood={attempt >= 2 ? 'thinking' : undefined} />
      {attempt === 1 && (
        <p>
          <span className="tag tag-neutral">두 번째 방법</span>
        </p>
      )}
      {facts.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="text-sm font-bold text-ink-900">확인된 것</h3>
          <ul className="space-y-1 text-body text-ink-900">
            {facts.map((l, i) => (
              <li key={i} className="break-keep">
                <AdviceText segments={l.segments} />
              </li>
            ))}
          </ul>
        </section>
      )}
      {suggestion.analysis && <Analysis analysis={suggestion.analysis} />}
      {guesses.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="text-sm font-bold text-ink-900">AI 조언</h3>
          <ul className="space-y-1 text-body text-ink-900">
            {guesses.map((l, i) => (
              <li key={i} className="flex items-start gap-1.5">
                <span className="tag tag-neutral mt-px">추정</span>
                <span className="min-w-0 break-keep">
                  <AdviceText segments={l.segments} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {attempt === 1 && <TriedList tried={suggestion.tried} />}
      <FactLines facts={suggestion.facts} />
      <div className="space-y-2">
        {suggestion.actions.map((a, i) => (
          <button
            key={a.index}
            type="button"
            disabled={busy}
            onClick={() =>
              accept.mutate(
                { id: suggestion.id, index: a.index },
                {
                  onSuccess: ({ action }) => {
                    onDone()
                    runAction(action)
                  },
                },
              )
            }
            // 한 화면 한 채움 — 첫 버튼만 채운다.
            className={`${i === 0 ? 'btn-primary' : 'btn-outline'} btn-md w-full`}
          >
            {a.label}
          </button>
        ))}
        <div className="flex justify-center">
          <button type="button" disabled={busy} onClick={() => dismiss.mutate(suggestion.id)} className="btn-text text-sm">
            이 제안 닫기
          </button>
        </div>
      </div>
      <StepsLog steps={suggestion.steps} />
    </article>
  )
}

/** 「핑고가 12분 전에 지도를 살펴봤어요」 — 1분 안이면 「방금」. */
function checkedLabel(iso: string): string {
  const ago = timeAgo(iso)
  return `핑고가 ${ago === '방금 전' ? '방금' : `${ago}에`} 지도를 살펴봤어요`
}

/**
 * 「핑고가 한 일」 — 이 제안을 만들며 거친 단계(#1297, agent-v2 11.3). 줄 모양은 AI 코스 작업 기록과 같은 `StepRow`다.
 * 서버 구현 전이거나 기록이 지워진 제안(탈퇴, 30일 정리)은 없거나 빈 목록이라 토글을 그리지 않는다.
 */
function StepsLog({ steps }: { steps?: WorkStepDto[] }) {
  const [open, setOpen] = useState(false)
  if (!steps?.length) return null
  return (
    <div className="space-y-2">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)} className="btn-link text-sm">
        {open ? '핑고가 한 일 접기' : '핑고가 한 일 보기'}
      </button>
      {open && (
        <ol aria-label="핑고가 한 일" className="space-y-2">
          {steps.map((step, i) => (
            <li key={i}>
              <StepRow step={step} />
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

/** 의견 갈림(split)의 충돌 지점. 이름 대신 ♥ 쪽 / 반대 쪽으로, 문구는 서버가 렌더한 그대로다(agent-v2 16.2). */
function Analysis({ analysis }: { analysis: AgentAnalysisDto }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-sm font-bold text-ink-900">어디서 갈리나요</h3>
      <p className="text-body text-ink-600">{CONFLICT_LABEL[analysis.conflict_type]}</p>
      {analysis.axes.length > 0 && (
        <ul className="divide-y divide-ink-100 rounded-xl ring-1 ring-ink-200">
          {analysis.axes.map((axis, i) => (
            <li key={i} className="space-y-0.5 px-3 py-2 text-body">
              <p className="font-semibold text-ink-900">{axis.label}</p>
              <p className="flex flex-wrap gap-x-3 text-xs">
                {axis.like_side && <span className="text-[var(--good-text)]">♥ 좋음 쪽 · {axis.like_side}</span>}
                {axis.against_side && (
                  <span className="text-[var(--bad-text)]">
                    <AgainstMark size={12} /> 반대 쪽 · {axis.against_side}
                  </span>
                )}
              </p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
