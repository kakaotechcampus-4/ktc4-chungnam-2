import type { components } from '@pingo/contracts/src/types/api'

export type AgentStateDto = components['schemas']['AgentState']
export type AgentSettingsDto = components['schemas']['AgentSettings']
export type AgentSuggestionDto = components['schemas']['AgentSuggestion']
export type AgentActionDto = components['schemas']['AgentAction']
export type AgentAdviceLineDto = components['schemas']['AgentAdviceLine']
export type AgentAnalysisDto = components['schemas']['AgentAnalysis']
export type AgentSummaryDto = components['schemas']['AgentSummary']
export type RunAdviceDto = components['schemas']['RunAdvice']

/** 의견 갈림의 충돌 종류(agent-v2 6.3). 종류는 코드가 정하고 화면은 이름만 붙인다. */
export const CONFLICT_LABEL: Record<AgentAnalysisDto['conflict_type'], string> = {
  same_axis: '같은 점을 두고 의견이 반대예요',
  different_axes: '서로 다른 점을 보고 있어요',
  unclear: '어느 점이 갈리는지 아직 분명하지 않아요',
}

/** 확인된 것(is_guess=false)과 AI 조언(추정, true)을 나눈다(agent-v2 16.2). */
export function splitAdvice(lines: AgentAdviceLineDto[]): { facts: AgentAdviceLineDto[]; guesses: AgentAdviceLineDto[] } {
  return { facts: lines.filter((l) => !l.is_guess), guesses: lines.filter((l) => l.is_guess) }
}

/** 지금 제안이 끝났을 때(수락·닫기·만료·무효화). 같은 이벤트가 두 번 와도 결과가 같다. */
export function withoutSuggestion(state: AgentStateDto, suggestionId: string): AgentStateDto {
  return state.active_suggestion?.id === suggestionId ? { ...state, active_suggestion: null, has_unseen: false } : state
}

/** 그 카테고리 요약을 갈아끼운다(agent.summary_updated). 없던 카테고리면 더한다. */
export function withSummary(state: AgentStateDto, summary: AgentSummaryDto): AgentStateDto {
  const known = state.summaries.some((s) => s.category === summary.category)
  return { ...state, summaries: known ? state.summaries.map((s) => (s.category === summary.category ? summary : s)) : [...state.summaries, summary] }
}
