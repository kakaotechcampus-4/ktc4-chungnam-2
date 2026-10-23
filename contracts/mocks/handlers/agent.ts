import { http, HttpResponse } from "msw";
import { ME_USER_ID, emitEvent, store, type AgentSettings, type RunAdvice } from "../store";
import { apiError } from "../util";

/**
 * v2 계획 보조 에이전트(docs/agent-v2.md, #510). 실서버 구현 전이라 목 서버가 계약을 먼저 연다.
 * 관찰(탐지, 모델 진단)은 서버 백그라운드 일이라 흉내 내지 않는다 — 시드의 제안과 요약을 그대로 내보낸다.
 * 에이전트는 아무것도 직접 실행하지 않는다: accept는 동작 설명만 돌려주고 FE가 기존 API로 실행한다.
 */

const DEFAULT_SETTINGS: AgentSettings = { enabled: true, updated_by: null, updated_at: null };

function settingsOf(mapId: string): AgentSettings {
  return store.agentSettings[mapId] ?? DEFAULT_SETTINGS;
}

function activeEntryOf(mapId: string) {
  return Object.values(store.agentSuggestions).find((e) => e.map_id === mapId && e.status === "active") ?? null;
}

/** 처리(수락, 닫기, 무효화)는 한 번만 — 이미 끝났으면 409 SUGGESTION_RESOLVED(docs/errors.md). */
function resolve(suggestionId: string, status: "accepted" | "dismissed" | "superseded", actionType: string | null) {
  const entry = store.agentSuggestions[suggestionId];
  entry.status = status;
  emitEvent(entry.map_id, "public", "agent.resolved", { suggestion_id: suggestionId, status, resolved_action_type: actionType });
}

/** 추천 막힘 조언 기본값 — 시나리오가 runAdvice에 넣어 두지 않았으면 결과가 3곳 미만일 때만 반경 조언을 낸다. */
function defaultAdvice(runId: string): RunAdvice | null {
  if ((store.candidates[runId] ?? []).length >= 3) return null;
  return {
    run_id: runId,
    kind: "radius",
    advice: [
      { segments: [{ kind: "text", text: "반경 밖에서 빠진 곳이 많아요" }], is_guess: false },
      { segments: [{ kind: "text", text: "걸어서 20분까지 넓히면 4곳이 더 후보가 돼요" }], is_guess: false },
    ],
    actions: [{ index: 0, type: "widen_radius", label: "반경 넓히기", params: { run_id: runId } }],
  };
}

export const agentHandlers = [
  http.get("*/maps/:mapId/agent", ({ params }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const settings = settingsOf(mapId);
    const entry = settings.enabled ? activeEntryOf(mapId) : null;
    return HttpResponse.json({
      settings,
      active_suggestion: entry?.suggestion ?? null,
      has_unseen: !!entry && !entry.viewed_by.includes(ME_USER_ID),
      summaries: store.agentSummaries[mapId] ?? [],
    });
  }),

  http.put("*/maps/:mapId/agent/settings", async ({ params, request }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const body = (await request.json()) as { enabled?: unknown };
    if (typeof body.enabled !== "boolean") return apiError(422, "VALIDATION_ERROR", "enabled는 true 또는 false");
    const settings: AgentSettings = { enabled: body.enabled, updated_by: ME_USER_ID, updated_at: new Date().toISOString() };
    store.agentSettings[mapId] = settings;
    const entry = activeEntryOf(mapId);
    if (!body.enabled && entry) resolve(entry.suggestion.id, "superseded", null); // 끄면 지금 제안은 무효화
    emitEvent(mapId, "public", "agent.settings_changed", { enabled: body.enabled, updated_by: ME_USER_ID });
    return HttpResponse.json(settings);
  }),

  http.post("*/agent/suggestions/:suggestionId/view", ({ params }) => {
    const entry = store.agentSuggestions[params.suggestionId as string];
    if (!entry) return apiError(404, "NOT_FOUND", "제안을 찾을 수 없습니다");
    if (!entry.viewed_by.includes(ME_USER_ID)) entry.viewed_by.push(ME_USER_ID);
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("*/agent/suggestions/:suggestionId/accept", async ({ params, request }) => {
    const suggestionId = params.suggestionId as string;
    const entry = store.agentSuggestions[suggestionId];
    if (!entry) return apiError(404, "NOT_FOUND", "제안을 찾을 수 없습니다");
    if (entry.status !== "active") return apiError(409, "SUGGESTION_RESOLVED", "이미 처리된 제안이에요");
    const body = (await request.json()) as { action_index?: unknown };
    const action = entry.suggestion.actions.find((a) => a.index === body.action_index);
    if (!action) return apiError(422, "VALIDATION_ERROR", "action_index가 제안의 버튼 범위 밖입니다");
    resolve(suggestionId, "accepted", action.type);
    return HttpResponse.json({ action });
  }),

  http.post("*/agent/suggestions/:suggestionId/dismiss", ({ params }) => {
    const suggestionId = params.suggestionId as string;
    const entry = store.agentSuggestions[suggestionId];
    if (!entry) return apiError(404, "NOT_FOUND", "제안을 찾을 수 없습니다");
    if (entry.status !== "active") return apiError(409, "SUGGESTION_RESOLVED", "이미 처리된 제안이에요");
    resolve(suggestionId, "dismissed", null);
    return new HttpResponse(null, { status: 204 });
  }),

  // recommend 태그지만 에이전트 조언이라 여기 둔다(docs/agent-v2.md 9절). run을 요청한 본인만.
  http.get("*/runs/:runId/advice", ({ params }) => {
    const runId = params.runId as string;
    const run = store.runs[runId];
    if (!run) return apiError(404, "NOT_FOUND", "run을 찾을 수 없습니다");
    if (store.runRequestedBy[runId] !== ME_USER_ID) return apiError(403, "FORBIDDEN", "추천을 요청한 사람만 볼 수 있어요");
    if (run.status !== "done") return new HttpResponse(null, { status: 204 });
    const advice = runId in store.runAdvice ? store.runAdvice[runId] : defaultAdvice(runId);
    if (!advice) return new HttpResponse(null, { status: 204 });
    return HttpResponse.json(advice);
  }),
];
