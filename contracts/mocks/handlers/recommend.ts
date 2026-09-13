import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type Pin } from "../store";
import { apiError } from "../util";
import { buildCandidates, buildEvidenceLines, buildRegions } from "../seed";

const CATEGORIES = ["음식점", "카페", "숙소", "관광지"] as const;

function requiredCount(mapId: string) {
  const n = store.members[mapId]?.length ?? 1;
  return Math.ceil(n / 2);
}

function findCandidateRun(candidateId: string) {
  for (const [runId, list] of Object.entries(store.candidates)) {
    const cand = list.find((c) => c.id === candidateId);
    if (cand) return { runId, cand, list };
  }
  return null;
}

/** 실행(③-a-2 필터 + ③-b 순위)을 흉내낸다 — 이미 결과가 시드돼 있으면 그대로 두고, 없으면 새로 만든다. */
function ensureCandidates(runId: string) {
  if (!(runId in store.candidates)) {
    const regionLabel = store.regions[runId]?.[0]?.label ?? "제주시 권역";
    store.candidates[runId] = buildCandidates(regionLabel);
  }
  return store.candidates[runId];
}

export const recommendHandlers = [
  http.get("*/maps/:mapId/recommend/readiness", ({ params }) => {
    const mapId = params.mapId as string;
    const required = requiredCount(mapId);
    const result: Record<string, { ready: boolean; answered_count: number; required_count: number }> = {};
    for (const category of CATEGORIES) {
      const pinsInCategory = Object.values(store.pins).filter((p) => p.map_id === mapId && p.category === category);
      const answeredUsers = new Set<string>();
      for (const pin of pinsInCategory) {
        if (!pin.id) continue;
        for (const r of store.reactions[pin.id] ?? []) answeredUsers.add(r.user_id!);
      }
      result[category] = { ready: answeredUsers.size >= required, answered_count: answeredUsers.size, required_count: required };
    }
    return HttpResponse.json(result);
  }),

  http.post("*/maps/:mapId/runs", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const body = (await request.json()) as { category: string };
    const runId = nextId("run");
    store.runs[runId] = { id: runId, map_id: mapId, category: body.category as any, status: "collecting_evidence", attempt_no: 1 };
    store.runRequestedBy[runId] = ME_USER_ID;
    // ② 사유 → 실격/선호/반경 구조화 (목 서버에서는 시드 데이터로 대체 — 실제 구조화는 backend/llm 담당)
    store.evidenceLines[runId] = buildEvidenceLines(runId);
    store.regions[runId] = buildRegions();
    return HttpResponse.json(store.runs[runId], { status: 202 });
  }),

  http.get("*/runs/:runId/evidence", ({ params }) => {
    const runId = params.runId as string;
    if (!store.runs[runId]) return apiError(404, "RUN_NOT_FOUND", "run을 찾을 수 없습니다");
    return HttpResponse.json(store.evidenceLines[runId] ?? []);
  }),

  http.patch("*/runs/:runId/evidence", async ({ params, request }) => {
    const runId = params.runId as string;
    const lines = store.evidenceLines[runId];
    if (!lines) return apiError(404, "RUN_NOT_FOUND", "run을 찾을 수 없습니다");
    const body = (await request.json()) as {
      toggle?: { id: string; is_active: boolean }[];
      add?: { text: string }[];
    };
    for (const t of body.toggle ?? []) {
      const line = lines.find((l) => l.id === t.id);
      // 5-5: 자기가 쓴 것만 뺄 수 있다
      if (line && line.author_id === ME_USER_ID) line.is_active = t.is_active;
    }
    for (const a of body.add ?? []) {
      lines.push({
        id: nextId("evi"),
        author_id: ME_USER_ID,
        author_display_name: store.users[ME_USER_ID]?.display_name ?? "나",
        text: a.text,
        badge: "reference",
        fact_key: null,
        is_active: true,
        permissions: { can_disable: true },
      });
    }
    return HttpResponse.json(lines);
  }),

  http.post("*/runs/:runId/regions/confirm", async ({ params, request }) => {
    const runId = params.runId as string;
    const regions = store.regions[runId];
    if (!regions) return apiError(404, "RUN_NOT_FOUND", "run을 찾을 수 없습니다");
    const body = (await request.json().catch(() => ({}))) as { accept_union?: boolean };
    const hasUnconfirmed = regions.some((r) => !r.confirmed);
    if (hasUnconfirmed && !body.accept_union) {
      return apiError(409, "REGION_CONFLICT", "두 조건을 동시에 만족하는 곳이 없어요", { regions });
    }
    regions.forEach((r) => (r.confirmed = true));
    const run = store.runs[runId];
    if (run) run.status = "executing";
    return HttpResponse.json(regions);
  }),

  http.post("*/runs/:runId/execute", ({ params }) => {
    const runId = params.runId as string;
    const run = store.runs[runId];
    if (!run) return apiError(404, "RUN_NOT_FOUND", "run을 찾을 수 없습니다");
    ensureCandidates(runId);
    run.status = "done";
    return HttpResponse.json(run, { status: 202 });
  }),

  http.get("*/runs/:runId/result", ({ params }) => {
    const runId = params.runId as string;
    const run = store.runs[runId];
    if (!run) return apiError(404, "RUN_NOT_FOUND", "run을 찾을 수 없습니다");
    const candidates = store.candidates[runId] ?? [];
    const funnel = [
      { label: "카테고리 후보 풀", removed_count: 0 },
      { label: "반경 밖 제거", removed_count: 3 },
      { label: "영업 종료 제거", removed_count: 1 },
      { label: "실격 조건 제거", removed_count: candidates.length === 0 ? 8 : 3 },
      { label: "이미 제안·거절됨", removed_count: 1 },
    ];
    if (candidates.length === 0) {
      return apiError(404, "NO_RESULTS", "필터에 걸리는 핀이 없어요", { funnel });
    }
    return HttpResponse.json({ run_id: runId, funnel, regions: store.regions[runId] ?? [], candidates });
  }),

  http.post("*/runs/:runId/widen", ({ params }) => {
    const runId = params.runId as string;
    const run = store.runs[runId];
    if (!run) return apiError(404, "RUN_NOT_FOUND", "run을 찾을 수 없습니다");
    run.status = "executing";
    // 가드레일 4·5-6-1: 기본값 원만 넓힌다 — 목 서버는 재계산 결과로 후보를 다시 채워 넣는다
    const regionLabel = store.regions[runId]?.[0]?.label ?? "제주시 권역";
    store.candidates[runId] = buildCandidates(regionLabel);
    run.status = "done";
    return new HttpResponse(null, { status: 202 });
  }),

  http.post("*/runs/:runId/retry", ({ params }) => {
    const runId = params.runId as string;
    const run = store.runs[runId];
    if (!run) return apiError(404, "RUN_NOT_FOUND", "run을 찾을 수 없습니다");
    if ((run.attempt_no ?? 1) >= 3) {
      return apiError(429, "RETRY_LIMIT", "3번까지만 찾습니다", { attempt_no: run.attempt_no });
    }
    run.attempt_no = (run.attempt_no ?? 1) + 1;
    run.status = "done";
    // 3절: 현재 뜬 대안 전체가 제외목록에 들어가고(목 서버는 별도 exclusions 컬렉션 없이 교체로 표현) 새로 채운다
    const regionLabel = store.regions[runId]?.[0]?.label ?? "제주시 권역";
    store.candidates[runId] = buildCandidates(regionLabel);
    return HttpResponse.json(run, { status: 202 });
  }),

  http.post("*/candidates/:candidateId/publish", ({ params }) => {
    const candidateId = params.candidateId as string;
    const found = findCandidateRun(candidateId);
    if (!found) return apiError(404, "AI_PIN_PRIVATE", "비공개 AI 후보를 찾을 수 없습니다");
    const { runId, cand } = found;
    const run = store.runs[runId];
    const pinId = nextId("pin");
    const pin: Pin = {
      id: pinId,
      map_id: run?.map_id ?? "",
      category: (run?.category as Pin["category"]) ?? "음식점",
      kind: "AI추천",
      visibility: "public",
      lat: 33.45,
      lng: 126.56,
      place_name: cand.place_name,
      checks: cand.checks, // 가드레일 5: 게시 후에도 근거를 그대로 유지
      source_run_id: runId,
      reaction_summary: { like: 0, neutral: 0, against: 0 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true },
    };
    store.pins[pinId] = pin;
    store.reactions[pinId] = [];
    cand.visibility = "published";
    cand.published_pin_id = pinId;
    return HttpResponse.json(pin);
  }),
];
