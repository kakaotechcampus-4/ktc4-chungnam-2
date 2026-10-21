import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type CourseRunEntity, type CourseRunMock } from "../store";
import { apiError } from "../util";

/**
 * AI 코스 짜기(#334, 팀 결정 #580 전 초안). 실서버 구현 전이라 목 서버가 계약을 먼저 연다.
 * 실제 엔진을 흉내 내지 않는다 — 확정 리스트의 핀을 날짜에 고르게 나눠 담고, 같은 날은 들어온 순서로 이은 뒤
 * 도보 시간은 직선거리 근사로 채운다. 진행 화면의 폴링을 보려고 첫 GET은 running, 그다음부터 done이다.
 * 영업시간을 아직 모르는 실서버와 같게 모든 장소가 「확인 필요」다(checks, needs_check).
 */

const DAILY_LIMIT = 5; // 사용자당 하루 요청 상한(KST 자정 초기화) — 목 서버는 시나리오가 바뀔 때까지 센다
const MIN_PLACES = 2;
const WALK_M_PER_MIN = 80;
const DAY_MS = 86_400_000;

function approxMinutes(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const dLat = (a.lat - b.lat) * 111_000;
  const dLng = (a.lng - b.lng) * 88_000;
  return Math.max(1, Math.round(Math.sqrt(dLat * dLat + dLng * dLng) / WALK_M_PER_MIN));
}

function tripDays(startDate: string, endDate: string): string[] {
  const start = Date.parse(`${startDate}T00:00:00Z`);
  const end = Date.parse(`${endDate}T00:00:00Z`);
  const n = Math.min(Math.max(Math.round((end - start) / DAY_MS) + 1, 1), 14);
  return Array.from({ length: n }, (_, i) => new Date(start + i * DAY_MS).toISOString().slice(0, 10));
}

const WEEKDAYS = "일월화수목금토";
const ORDINALS = ["첫째", "둘째", "셋째", "넷째", "다섯째", "여섯째", "일곱째"];
function dayLabel(date: string, i: number) {
  return `${ORDINALS[i] ?? `${i + 1}번째`} 날 (${WEEKDAYS[new Date(`${date}T00:00:00Z`).getUTCDay()]})`;
}

/** 이 지도의 확정 핀을 좌표를 아는 것(routable)과 모르는 것(live)으로 나눈다. */
function confirmedPins(mapId: string) {
  const items = store.shortlist[mapId] ?? [];
  const routable: { id: string; name: string; lat: number; lng: number }[] = [];
  const excluded: CourseRunMock["excluded"] = [];
  for (const item of items) {
    const pin = item.pin;
    if (pin.lat !== undefined && pin.lng !== undefined && pin.source !== "live") {
      routable.push({ id: pin.id, name: pin.place_name ?? "이 장소", lat: pin.lat, lng: pin.lng });
    } else {
      excluded.push({ pin_id: pin.id, reason: "NO_COORDINATES", text: "좌표를 알 수 없어 동선에서 빠졌어요" });
    }
  }
  return { routable, excluded, allIds: items.map((i) => i.pin.id) };
}

function buildRun(mapId: string, requestText: string, routable: ReturnType<typeof confirmedPins>["routable"], excluded: CourseRunMock["excluded"]): CourseRunMock {
  const map = store.maps[mapId];
  const dates = tripDays(map.start_date, map.end_date);
  const perDay = Math.ceil(routable.length / dates.length);
  const days: CourseRunMock["days"] = dates.map((date, d) => {
    const pins = routable.slice(d * perDay, (d + 1) * perDay);
    return {
      date,
      slots: pins.map((p, k) => ({ pin_id: p.id, order: k + 1, needs_check: true })),
      legs: pins.slice(1).map((p, k) => ({ from_pin_id: pins[k].id, to_pin_id: p.id, approx_minutes: approxMinutes(pins[k], p) })),
    };
  });
  const wantsLightWalk = requestText.includes("걷") || requestText.includes("덜");
  const goals: CourseRunMock["goals"] = wantsLightWalk
    ? [{ id: "daily_walk_low", kind: "daily_walk_low", label: "하루 걷는 시간 줄이기", met: true }]
    : [];
  const unmatched = requestText && !wantsLightWalk ? [requestText] : [];
  const now = new Date().toISOString();
  const byName = new Map(routable.map((p) => [p.id, p.name]));
  return {
    id: "",
    map_id: mapId,
    status: "done",
    outcome: "solved_with_checks",
    failure_code: null,
    goals,
    unmatched,
    steps: [
      { stage: "이해", by: "모델", text: `이렇게 이해했어요: ${goals.map((g) => g.label).join(" · ") || "요청 목표 없음"}${unmatched.map((u) => ` · 「${u}」는 그대로는 판단할 수 없어요`).join("")}` },
      { stage: "짜기", by: "코드", text: `후보 c1: 지킴 ${goals.map((g) => g.label).join(", ") || "없음"} · 못 지킴 없음 · 확정 위반 0` },
      { stage: "끝", by: "모델", text: "후보 c1로 끝내요" },
      { stage: "결과", by: "코드", text: "지킨 목표: " + (goals.map((g) => g.label).join(", ") || "없음") + " · 확정 위반 0 · 결과 solved_with_checks" },
    ],
    days,
    violations: [],
    checks: days.flatMap((day, d) =>
      day.slots.map((s) => ({ pin_id: s.pin_id, text: `${byName.get(s.pin_id) ?? "이 장소"}은(는) ${dayLabel(day.date, d)}에 영업하는지 알 수 없어요. 가게에 직접 확인해 주세요` })),
    ),
    excluded,
    snapshot_at: now,
    stale: false,
    created_at: now,
    finished_at: now,
  };
}

/** 응답에 싣는 값 — 진행 중이면 결과 칸을 비운다. stale은 지금 확정 리스트와 비교해 계산한다. */
function view(entry: CourseRunEntity): CourseRunMock {
  const run = entry.run;
  const current = (store.shortlist[run.map_id] ?? []).map((i) => i.pin.id);
  const stale = current.length !== entry.snapshot_pin_ids.length || current.some((id) => !entry.snapshot_pin_ids.includes(id));
  if (run.status === "done" || run.status === "failed") return { ...run, stale };
  return { ...run, outcome: null, goals: [], unmatched: [], steps: [], days: [], violations: [], checks: [], excluded: [], finished_at: null, stale };
}

function advance(entry: CourseRunEntity) {
  entry.polls += 1;
  entry.run.status = entry.polls === 1 ? "running" : "done";
  return view(entry);
}

export const courseHandlers = [
  http.post("*/maps/:mapId/courses", async ({ params, request }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const body = ((await request.json().catch(() => ({}))) ?? {}) as { request_text?: unknown };
    const requestText = typeof body.request_text === "string" ? body.request_text.trim() : "";
    if (requestText.length > 100) return apiError(422, "VALIDATION_ERROR", "request_text는 100자 이하");
    const { routable, excluded, allIds } = confirmedPins(mapId);
    if (routable.length < MIN_PLACES) {
      return apiError(422, "COURSE_NOT_ENOUGH_PLACES", "코스를 짤 확정 장소가 부족합니다", { min: MIN_PLACES, count: routable.length });
    }
    const mine = Object.values(store.courseRuns).filter((e) => e.requested_by === ME_USER_ID);
    const active = mine.find((e) => e.run.map_id === mapId && (e.run.status === "queued" || e.run.status === "running"));
    if (active) return apiError(409, "COURSE_IN_PROGRESS", "이미 짜는 중인 코스가 있습니다", { course_run_id: active.run.id });
    if (mine.length >= DAILY_LIMIT) return apiError(429, "COURSE_LIMIT", "하루 코스 요청 상한을 넘었습니다", { limit: DAILY_LIMIT, used: mine.length });
    const run = buildRun(mapId, requestText, routable, excluded);
    run.id = nextId("course");
    run.status = "queued";
    store.courseRuns[run.id] = { run, requested_by: ME_USER_ID, polls: 0, snapshot_pin_ids: allIds };
    return HttpResponse.json({ course_run_id: run.id }, { status: 202 });
  }),

  // 정적 경로(latest)를 먼저 둔다
  http.get("*/maps/:mapId/courses/latest", ({ params }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const mine = Object.values(store.courseRuns).filter((e) => e.requested_by === ME_USER_ID && e.run.map_id === mapId);
    const latest = mine[mine.length - 1];
    if (!latest) return new HttpResponse(null, { status: 204 });
    return HttpResponse.json(advance(latest));
  }),

  http.get("*/course-runs/:runId", ({ params }) => {
    const entry = store.courseRuns[params.runId as string];
    if (!entry) return apiError(404, "NOT_FOUND", "코스를 찾을 수 없습니다");
    if (entry.requested_by !== ME_USER_ID) return apiError(403, "FORBIDDEN", "권한이 없습니다");
    return HttpResponse.json(advance(entry));
  }),
];
