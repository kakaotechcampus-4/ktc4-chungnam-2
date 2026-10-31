import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/api'
import { showToast } from '@/features/shell/toast'

import { acceptSuggestion, dismissSuggestion, fetchAgent, fetchRunAdvice, putAgentSettings, viewSuggestion } from './api'
import { withSummary, withoutSuggestion, type AgentSettingsDto, type AgentStateDto, type AgentSummaryDto, type AgentSuggestionDto } from './model'

/** ['maps', mapId] 아래에 두지 않는다 — 지도 상세를 무효화할 때(member.joined 등) 같이 다시 받지 않게. */
export const agentKeys = {
  state: (mapId: string) => ['agent', mapId] as const,
  advice: (runId: string) => ['runs', runId, 'advice'] as const,
}

/** 「핑고 AI 조언」 상태. 지도에 들어오면 받고, 이후는 agent.* 이벤트 페이로드로 고친다(docs/events.md). */
export function useAgentQuery(mapId: string) {
  return useQuery({ queryKey: agentKeys.state(mapId), queryFn: () => fetchAgent(mapId) })
}

function useAgentCache(mapId: string) {
  const queryClient = useQueryClient()
  return {
    update: (fn: (s: AgentStateDto) => AgentStateDto) => queryClient.setQueryData<AgentStateDto>(agentKeys.state(mapId), (s) => s && fn(s)),
    refetch: () => queryClient.invalidateQueries({ queryKey: agentKeys.state(mapId) }),
  }
}

export function useAgentSettingsMutation(mapId: string) {
  const cache = useAgentCache(mapId)
  return useMutation({
    mutationFn: (enabled: boolean) => putAgentSettings(mapId, enabled),
    // 끄면 서버가 지금 제안을 무효화한다(api-spec). 이벤트를 기다리지 않고 바로 비운다.
    onSuccess: (settings) => cache.update((s) => (settings.enabled ? { ...s, settings } : { ...s, settings, active_suggestion: null, has_unseen: false })),
    onError: () => showToast('설정을 바꾸지 못했어요'),
  })
}

/** 시트에서 제안을 봤다 — 버튼의 점을 끈다. 화면에 남는 동작이 아니라 실패해도 알리지 않고 기록만 남긴다(점이 그대로 남는다). */
export function useViewSuggestionMutation(mapId: string) {
  const cache = useAgentCache(mapId)
  return useMutation({
    mutationFn: viewSuggestion,
    onSuccess: () => cache.update((s) => ({ ...s, has_unseen: false })),
    onError: (err) => console.error('[agent] 열람 기록 실패', err),
  })
}

/**
 * 수락·닫기 공통 실패 처리. 409 SUGGESTION_RESOLVED 는 다른 구성원이 먼저 처리한 것 — 상태를 다시 받아 시트를 고친다(docs/errors.md).
 */
function useResolveError(mapId: string) {
  const cache = useAgentCache(mapId)
  return (err: Error) => {
    if (err instanceof ApiError && err.code === 'SUGGESTION_RESOLVED') {
      void cache.refetch()
      showToast('다른 구성원이 먼저 처리한 제안이에요')
      return
    }
    showToast('제안을 처리하지 못했어요')
  }
}

export function useAcceptSuggestionMutation(mapId: string) {
  const cache = useAgentCache(mapId)
  return useMutation({
    mutationFn: ({ id, index }: { id: string; index: number }) => acceptSuggestion(id, index),
    onSuccess: (_res, { id }) => cache.update((s) => withoutSuggestion(s, id)),
    onError: useResolveError(mapId),
  })
}

export function useDismissSuggestionMutation(mapId: string) {
  const cache = useAgentCache(mapId)
  return useMutation({
    mutationFn: (id: string) => dismissSuggestion(id),
    onSuccess: (_res, id) => cache.update((s) => withoutSuggestion(s, id)),
    onError: useResolveError(mapId),
  })
}

/**
 * agent.* 이벤트를 페이로드로 상태에 적용한다(docs/events.md 다시 받기 표, agent-v2 16.4). 모두 덮어쓰기라 두 번 와도 같다.
 * 시트가 열려 있으면 시트가 has_unseen 을 보고 바로 view 를 부른다 — 여기서는 점만 켠다.
 */
export function agentEventHandlers(queryClient: QueryClient, mapId: string): Record<string, (e: MessageEvent) => void> {
  const update = (fn: (s: AgentStateDto) => AgentStateDto) => queryClient.setQueryData<AgentStateDto>(agentKeys.state(mapId), (s) => s && fn(s))
  const data = <T>(e: MessageEvent) => JSON.parse(e.data) as T
  return {
    'agent.suggested': (e) => {
      const suggestion = data<AgentSuggestionDto>(e)
      update((s) => (s.active_suggestion?.id === suggestion.id ? s : { ...s, active_suggestion: suggestion, has_unseen: true }))
    },
    // 요약 갱신은 점을 켜지 않는다.
    'agent.summary_updated': (e) => update((s) => withSummary(s, data<AgentSummaryDto>(e))),
    'agent.resolved': (e) => update((s) => withoutSuggestion(s, data<{ suggestion_id: string }>(e).suggestion_id)),
    'agent.settings_changed': (e) => {
      const { enabled, updated_by } = data<Pick<AgentSettingsDto, 'enabled' | 'updated_by'>>(e)
      update((s) => ({
        ...s,
        settings: { ...s.settings, enabled, updated_by },
        ...(enabled ? {} : { active_suggestion: null, has_unseen: false }),
      }))
    },
  }
}

/**
 * 추천 막힘 조언(agent-v2 16.5). run 당 한 번 만들어 저장되니 다시 받지 않는다. 대상이 아니면 204(null).
 * 실패(500)는 다음 요청이 다시 만든다 — 조언 자리를 숨기고 기록만 남긴다.
 */
export function useRunAdviceQuery(runId: string) {
  return useQuery({
    queryKey: agentKeys.advice(runId),
    queryFn: () => fetchRunAdvice(runId),
    staleTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
  })
}
