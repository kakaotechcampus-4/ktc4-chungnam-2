import { useEffect } from 'react'

import ErrorText from '@/ErrorText'
import { useMembersQuery } from '@/features/maps/queries'
import { AiHeader } from '@/features/recommend/Readiness'
import ModalSheet from '@/features/shell/ModalSheet'
import AgainstMark from '@/ui/AgainstMark'
import PingoLoading from '@/ui/PingoLoading'
import SheetTitle from '@/ui/SheetTitle'
import Switch from '@/ui/Switch'

import { useRunAgentAction } from './actions'
import AdviceText from './AdviceText'
import { CONFLICT_LABEL, splitAdvice, type AgentAnalysisDto, type AgentSuggestionDto } from './model'
import {
  useAcceptSuggestionMutation,
  useAgentQuery,
  useAgentSettingsMutation,
  useDismissSuggestionMutation,
  useViewSuggestionMutation,
} from './queries'

/**
 * 「핑고 AI 조언」 바텀시트(agent-v2 16.2). 위에서부터 모드 스위치 → 지금 제안(0개 또는 1개).
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
        {query.error && <ErrorText message="조언을 불러오지 못했어요" error={query.error} />}
        {state && !enabled && (
          <p className="text-body text-ink-600">
            꺼져 있어요{changer && ` · ${changer.isMe ? '내가' : `${changer.name}님이`} 껐어요`}. 켜면 지도가 막힌 곳을 찾아 구성원 모두에게 제안해요
          </p>
        )}
        {state && enabled && state.active_suggestion && <Suggestion mapId={mapId} suggestion={state.active_suggestion} onDone={onClose} />}
        {state && enabled && !state.active_suggestion && <AiHeader title="지금은 따로 드릴 제안이 없어요" sub="막힌 곳이 보이면 여기에 알려 드릴게요" />}
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

  return (
    <article className="space-y-3">
      <AiHeader title={suggestion.title} sub="구성원 모두에게 같은 제안이 보여요" />
      {facts.length > 0 && (
        <section className="space-y-1.5">
          <h3 className="text-sm font-bold text-ink-900">확인된 것</h3>
          <ul className="space-y-1 text-body text-ink-900">
            {facts.map((l, i) => (
              <li key={i} className="break-keep">
                <AdviceText line={l} />
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
                  <AdviceText line={l} />
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
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
    </article>
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
