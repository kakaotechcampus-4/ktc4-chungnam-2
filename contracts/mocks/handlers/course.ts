import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type CourseRunEntity, type CourseRunMock } from "../store";
import { apiError } from "../util";
import { chargeCredit, creditGate } from "./credits";
import { scheduleVersion } from "./shortlist";

/**
 * AI 코스 짜기(#334, 팀 결정 #580 전 초안). 실서버 구현 전이라 목 서버가 계약을 먼저 연다.
 * 실제 엔진을 흉내 내지 않는다 — 확정 리스트의 핀을 날짜에 고르게 나눠 담고, 같은 날은 들어온 순서로 이은 뒤
 * 구간은 직선거리 근사로 채운다(2km 이하는 도보, 넘으면 대중교통). 진행 화면의 폴링을 보려고 첫 GET은 running(단계 2개), 둘째는 running(단계 5개 — 찾기·옮겨 보기 포함), 셋째부터 done(14개)이다 — 진행 중에도 steps가 단계마다 늘어난다.
 * 영업시간을 아직 모르는 실서버와 같게 모든 장소가 「확인 필요」다(checks, needs_check).
 *
 * 일정 기준 모드(#1237): 요청 때 확정 장소(좌표를 아는 것)의 날짜 배정으로 mode가 정해진다 — 하나도 안 넣었으면 plan(위의 짜기),
 * 일부만 넣었으면 fill(넣은 장소는 그 날에 두고 미배정을 날짜 수가 가장 적은 날에 둔다 + 「○일째에 넣기」 카드),
 * 모두 넣었으면 review(일정 그대로 + 고칠 점 카드: 날 맞바꾸기 1, 1곳 옮기기 1, 고치지 않기로 한 것 1). 카드 내용은 고정 예시이고 실제 계산과 맞추지 않는다.
 * 카드를 「반영」해도 목 서버의 코스는 그대로다 — FE가 일정 PUT으로 저장하면 일정 version이 달라져 stale이 된다.
 */

// 하루 상한(429 COURSE_LIMIT)은 크레딧으로 바뀌었다(#432 D3). 목 서버의 코스는 실패하지 않아 환불(refundCredit)을 부를 자리가 없다
const MIN_PLACES = 2;
const WALK_M_PER_MIN = 80;
const WALK_MAX_M = 2_000; // 서버 초안 규칙: 직선거리 2km 이하는 walk, 넘으면 transit
const TRANSIT_M_PER_MIN = 333; // 약 20km/h
const TRANSIT_OVERHEAD_MIN = 10;
const DAY_MS = 86_400_000;

/** 구간 방식과 분 — 서버와 같은 규칙(직선거리 기준 거친 추정). */
function leg(a: { lat: number; lng: number }, b: { lat: number; lng: number }): { mode: "walk" | "transit"; approx_minutes: number } {
  const dLat = (a.lat - b.lat) * 111_000;
  const dLng = (a.lng - b.lng) * 88_000;
  const meters = Math.sqrt(dLat * dLat + dLng * dLng);
  if (meters <= WALK_MAX_M) return { mode: "walk", approx_minutes: Math.max(1, Math.round(meters / WALK_M_PER_MIN)) };
  return { mode: "transit", approx_minutes: Math.max(1, Math.round(meters / TRANSIT_M_PER_MIN + TRANSIT_OVERHEAD_MIN)) };
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
  const routable: { id: string; name: string; lat: number; lng: number; date: string | null; order: number }[] = [];
  const excluded: CourseRunMock["excluded"] = [];
  for (const item of items) {
    const pin = item.pin;
    if (pin.lat !== undefined && pin.lng !== undefined && pin.source !== "live") {
      const scheduled = item as { scheduled_date?: string | null; visit_order?: number | null };
      routable.push({ id: pin.id, name: pin.place_name ?? "이 장소", lat: pin.lat, lng: pin.lng, date: scheduled.scheduled_date ?? null, order: scheduled.visit_order ?? 1e9 });
    } else {
      excluded.push({ pin_id: pin.id, reason: "NO_COORDINATES", text: "좌표를 알 수 없어 동선에서 빠졌어요" });
    }
  }
  return { routable, excluded };
}

type Routable = ReturnType<typeof confirmedPins>["routable"];

function modeOf(routable: Routable): CourseRunMock["mode"] {
  const dated = routable.filter((p) => p.date !== null).length;
  return dated === 0 ? "plan" : dated === routable.length ? "review" : "fill";
}

/** 날짜별 장소 — plan은 고르게 나누고, fill은 넣어 둔 장소를 두고 미배정을 가장 적은 날에, review는 일정 그대로. */
function layout(mode: CourseRunMock["mode"], dates: string[], routable: Routable): Routable[] {
  if (mode === "plan") {
    const perDay = Math.ceil(routable.length / dates.length);
    return dates.map((_, d) => routable.slice(d * perDay, (d + 1) * perDay));
  }
  const byDate = dates.map((date) => routable.filter((p) => p.date === date).sort((a, b) => a.order - b.order));
  for (const pin of routable.filter((p) => p.date === null)) {
    const fewest = byDate.reduce((best, pins, i) => (pins.length < byDate[best].length ? i : best), 0);
    byDate[fewest].push(pin);
  }
  return byDate;
}

/** fill: 미배정 장소마다 「○일째에 넣기」, review: 고칠 점 3개(날 맞바꾸기, 1곳 옮기기, 고치지 않음). 문장은 고정 예시다. */
function exampleFixes(mode: CourseRunMock["mode"], dates: string[], routable: Routable, byDate: Routable[]): Pick<CourseRunMock, "fixes" | "checked"> {
  const label = (i: number) => dayLabel(dates[i], i);
  if (mode === "fill") {
    const fixes: CourseRunMock["fixes"] = routable.flatMap((p, k) => {
      const i = byDate.findIndex((pins) => pins.includes(p));
      if (p.date !== null) return [];
      return [{
        id: `fix_${k + 1}`, kind: "unassigned" as const, strength: "soft" as const,
        text: `${p.name}은(는) 아직 날짜에 넣지 않았어요`,
        moves: [{ pin_id: p.id, from_date: null, to_date: dates[i] }],
        resolved_text: `${label(i)}에 넣으면 그날 이동이 가장 짧아요`, remaining_text: null, not_fixed_reason: null,
      }];
    });
    return { fixes, checked: [{ kind: "closed", text: "쉬는 날에 넣은 곳은 없어요" }, { kind: "travel", text: "도보·이동 상한을 넘는 날은 없어요" }] };
  }
  const full = byDate.map((pins, i) => ({ pins, i })).filter((d) => d.pins.length > 0);
  if (full.length < 2) {
    return { fixes: [], checked: ["closed", "travel", "member", "condition", "goal", "cluster", "meal"].map((kind) => ({ kind: kind as CourseRunMock["checked"][number]["kind"], text: "문제 없어요" })) };
  }
  const [a, b] = full; // 날 맞바꾸기: 앞의 두 날을 통째로
  const swap = [...a.pins.map((p) => ({ pin_id: p.id, from_date: dates[a.i], to_date: dates[b.i] })), ...b.pins.map((p) => ({ pin_id: p.id, from_date: dates[b.i], to_date: dates[a.i] }))];
  const fixes: CourseRunMock["fixes"] = [{
    id: "fix_1", kind: "closed", strength: "hard",
    text: `${b.pins[0].name}은(는) ${label(b.i)}에 쉬어요`,
    moves: swap,
    resolved_text: `${label(a.i)}과(와) ${label(b.i)}을(를) 통째로 바꾸면 ${b.pins[0].name} 휴무 문제가 해결돼요`,
    remaining_text: null, not_fixed_reason: null,
  }];
  const crowded = full.find((d) => d.pins.length >= 2); // 1곳 옮기기: 가장 먼저 나오는 2곳 이상인 날의 마지막 장소를 다른 날로
  if (crowded) {
    const target = dates.findIndex((_, i) => i !== crowded.i);
    const moved = crowded.pins[crowded.pins.length - 1];
    fixes.push({
      id: "fix_2", kind: "travel", strength: "hard",
      text: `${label(crowded.i)}은 하루 도보가 상한(150분)을 넘어요`,
      moves: [{ pin_id: moved.id, from_date: dates[crowded.i], to_date: dates[target] }],
      resolved_text: `${moved.name}만 ${label(target)}로 옮기면 하루 도보가 줄어 상한 안이에요`,
      remaining_text: "둘째 날 대중교통 이동은 그대로예요", not_fixed_reason: null,
    });
  }
  if (routable.length >= 3) {
    fixes.push({
      id: `fix_${fixes.length + 1}`, kind: "meal", strength: "soft",
      text: `${label(full[full.length - 1].i)}에는 식당이 없어요`,
      moves: [], resolved_text: null, remaining_text: null,
      not_fixed_reason: "고치려면 2곳을 옮겨야 하고 다른 날 이동이 늘어서 그대로 둬요",
    });
  }
  const open = routable.length >= 3 ? ["member", "condition", "goal", "cluster"] : ["member", "condition", "goal", "cluster", "meal"];
  return { fixes, checked: open.map((kind) => ({ kind: kind as CourseRunMock["checked"][number]["kind"], text: "문제 없어요" })) };
}

const HEADLINE: Record<CourseRunMock["mode"], (n: number) => string> = {
  plan: () => "날짜별 코스를 짰어요",
  fill: (n) => `넣어 둔 일정은 그대로 두고 남은 ${n}곳을 채워 봤어요`,
  review: (n) => (n === 0 ? "일정을 점검했어요. 고칠 점이 없어요" : `일정을 점검했어요. 고칠 점 ${n}개`),
};

/** fill·review 작업 기록 — 사람이 넣은 장소를 먼저 고정하고 점검한다. 진행 중 조회(2줄, 5줄)가 되도록 5줄 이상이다. */
function scheduleSteps(mode: "fill" | "review", routable: Routable, fixes: CourseRunMock["fixes"], goalText: string): CourseRunMock["steps"] {
  const fixed = routable.filter((p) => p.date !== null).length;
  const steps: CourseRunMock["steps"] = [
    { stage: "이해", role: "해석", by: "ai", by_detail: null, text: `이렇게 이해했어요: ${goalText === "없음" ? "요청 목표 없음" : goalText}` },
    { stage: "고정", role: "검증", by: "code", by_detail: null, text: `사람이 날짜에 넣은 ${fixed}곳은 그 날에 두고 바꾸지 않아요.` },
  ];
  if (mode === "fill") {
    steps.push(
      { stage: "짜기", role: "계산", by: "code", by_detail: null, text: `남은 ${routable.length - fixed}곳을 넣어 둔 날의 이동이 짧은 날에 나눴어요.` },
      { stage: "점검", role: "검증", by: "code", by_detail: null, text: "넣어 둔 일정에 쉬는 날이나 이동 과다가 있는지 확인했어요." },
      { stage: "비교", role: "검증", by: "code", by_detail: null, text: "미배정 장소마다 어느 날에 넣을지 하루 이동으로 견줬어요." },
    );
  } else {
    steps.push(
      { stage: "점검", role: "검증", by: "code", by_detail: null, text: `일정을 점검했어요. 하드 문제 ${fixes.filter((f) => f.strength === "hard").length}개, 선호 문제 ${fixes.filter((f) => f.strength === "soft").length}개를 찾았어요.` },
      { stage: "옮겨 보기", role: "계산", by: "code", by_detail: null, text: "쉬는 날 문제는 두 날을 통째로 바꿔 보는 중이에요." },
      { stage: "옮겨 보기", role: "계산", by: "code", by_detail: null, text: "도보 문제는 1곳만 옮겨 보는 중이에요." },
      { stage: "결정", role: "결정", by: "code", by_detail: null, text: "덜 건드리는 수에서 풀려서 거기서 멈췄어요." },
    );
  }
  steps.push({ stage: "결과", role: "계산", by: "code", by_detail: null, text: `고칠 점 ${fixes.length}개를 카드로 냈어요. 반영은 카드마다 눌러야 일정에 들어가요.` });
  return steps;
}

function buildRun(mapId: string, requestText: string, routable: Routable, excluded: CourseRunMock["excluded"]): CourseRunMock {
  const map = store.maps[mapId];
  const dates = tripDays(map.start_date, map.end_date);
  const mode = modeOf(routable);
  const byDate = layout(mode, dates, routable);
  const days: CourseRunMock["days"] = dates.map((date, d) => {
    const pins = byDate[d];
    return {
      date,
      slots: pins.map((p, k) => ({ pin_id: p.id, order: k + 1, needs_check: true })),
      legs: pins.slice(1).map((p, k) => ({ from_pin_id: pins[k].id, to_pin_id: p.id, ...leg(pins[k], p) })),
    };
  });
  const { fixes, checked } = mode === "plan" ? { fixes: [], checked: [] } : exampleFixes(mode, dates, routable, byDate);
  const wantsLightWalk = requestText.includes("걷") || requestText.includes("덜");
  const goals: CourseRunMock["goals"] = wantsLightWalk
    ? [{ id: "daily_walk_low", kind: "daily_walk_low", label: "하루 걷는 시간 줄이기", met: true }]
    : [];
  const unmatched = requestText && !wantsLightWalk ? [requestText] : [];
  const now = new Date().toISOString();
  const byName = new Map(routable.map((p) => [p.id, p.name]));
  const goalText = goals.map((g) => `‘${g.label}’`).join(", ") || "없음";
  const transit = days.reduce((n, d) => n + d.legs.filter((l) => l.mode === "transit").length, 0);
  const second = dates.length > 1 ? dayLabel(dates[1], 1) : dayLabel(dates[0], 0);
  const moved = routable[routable.length - 1].name;
  return {
    id: "",
    map_id: mapId,
    status: "done",
    mode,
    outcome: "solved_with_checks",
    failure_code: null,
    headline: HEADLINE[mode](fixes.length),
    goals,
    unmatched,
    // 실서버 작업 기록(agent/course/worklog.py)의 단계 흐름을 흉내 낸다 — 찾기·옮겨 보기·결정·비교·끝·가정 줄이 있어야 진행 화면의 줄 색과
    // 단계 막대를 목 서버로 볼 수 있다(#1243). 문장은 고정 예시이고 계산과 맞추지 않는다. 진행 중 두 번째 조회(5줄)에 찾기·옮겨 보기가 보인다.
    steps: mode !== "plan" ? scheduleSteps(mode, routable, fixes, goalText) : [
      { stage: "이해", role: "해석", by: "ai", by_detail: null, text: `이렇게 이해했어요: ${goals.map((g) => g.label).join(" · ") || "요청 목표 없음"}${unmatched.map((u) => ` · 「${u}」는 그대로는 판단할 수 없어요`).join("")}` },
      { stage: "확인", role: "검증", by: "code", by_detail: null, text: "요청한 목표가 이 장소들로 가능한지 데이터와 맞춰 봤어요" },
      { stage: "짜기", role: "지휘", by: "ai", by_detail: "모델 → 코드", text: "목표에 맞춰 짜 볼게요" },
      { stage: "찾기", role: "검증", by: "code", by_detail: null, text: `${second}엔 이동 위반이 남았어요. 이동을 줄이는 나누기를 1가지 찾았어요.` },
      { stage: "옮겨 보기", role: "계산", by: "code", by_detail: null, text: `${moved}을(를) 다른 날로 옮겨 짜 보면 확정 위반 0개, 하루 도보 최대 30분이에요.` },
      { stage: "결정", role: "결정", by: "code", by_detail: null, text: `${moved}을(를) 옮기는 나누기로 정했어요.` },
      { stage: "짜기", role: "계산", by: "code", by_detail: null, text: `1번 안을 짰어요. 지킨 목표는 ${goalText}예요. 하루 걷는 시간은 길어야 30분이에요. 대중교통 ${transit}구간. 확정 위반은 없어요.` },
      { stage: "짜기", role: "계산", by: "code", by_detail: null, text: "2번 안을 짰어요. 하루 걷는 시간은 길어야 25분이에요. 확정 위반은 없어요." },
      { stage: "점검", role: "지휘", by: "ai", by_detail: null, text: "목표를 지킨 1번 안을 골라요." },
      { stage: "비교", role: "검증", by: "code", by_detail: null, text: `1번 안(요청 목표를 최대한): 목표 ${goals.length}개 중 ${goals.length}개 지킴, 확정 위반 0개, 하루 도보 최대 30분.` },
      { stage: "비교", role: "검증", by: "code", by_detail: null, text: "2번 안(요청 목표 없이 이동과 날짜 균형 먼저): 확정 위반 0개, 하루 도보 최대 25분." },
      { stage: "끝", role: "지휘", by: "ai", by_detail: null, text: "2번 안은 걷기는 짧지만 요청 목표를 덜 지켜서 1번 안으로 정했어요." },
      { stage: "가정", role: "결정", by: "code", by_detail: null, text: "영업시간을 모르는 곳은 묻지 않고 여는 것으로 보고 정했어요." },
      { stage: "결과", role: "계산", by: "code", by_detail: null, text: `지킨 목표는 ${goalText}예요. 확정 위반은 없어요. 영업시간을 모르는 ${routable.length}곳은 가게에 확인해 주세요.` },
    ],
    days,
    fixes,
    checked,
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

/** 진행 중 GET이 돌려주는 steps 개수 — 폴링마다 늘어난다(실서버는 단계가 생길 때마다 늘어난다). */
const RUNNING_STEP_COUNTS = [2, 5];

/** 응답에 싣는 값 — 진행 중이면 결과 칸을 비우고 steps만 지금까지의 것을 싣는다. stale은 요청 때 일정 version과 지금 version을 비교한다(#1237). */
function view(entry: CourseRunEntity): CourseRunMock {
  const run = entry.run;
  const stale = scheduleVersion(run.map_id) !== entry.snapshot_version;
  if (run.status === "done" || run.status === "failed") return { ...run, stale };
  const shown = RUNNING_STEP_COUNTS[Math.min(Math.max(entry.polls, 1), RUNNING_STEP_COUNTS.length) - 1] ?? 0;
  return { ...run, outcome: null, headline: null, goals: [], unmatched: [], steps: run.steps.slice(0, shown), days: [], fixes: [], checked: [], violations: [], checks: [], excluded: [], finished_at: null, stale };
}

function advance(entry: CourseRunEntity) {
  entry.polls += 1;
  entry.run.status = entry.polls <= RUNNING_STEP_COUNTS.length ? "running" : "done";
  return view(entry);
}

export const courseHandlers = [
  http.post("*/maps/:mapId/courses", async ({ params, request }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const body = ((await request.json().catch(() => ({}))) ?? {}) as { request_text?: unknown };
    const requestText = typeof body.request_text === "string" ? body.request_text.trim() : "";
    if (requestText.length > 100) return apiError(422, "VALIDATION_ERROR", "request_text는 100자 이하");
    const { routable, excluded } = confirmedPins(mapId);
    if (routable.length < MIN_PLACES) {
      return apiError(422, "COURSE_NOT_ENOUGH_PLACES", "코스를 짤 확정 장소가 부족합니다", { min: MIN_PLACES, count: routable.length });
    }
    const mine = Object.values(store.courseRuns).filter((e) => e.requested_by === ME_USER_ID);
    const active = mine.find((e) => e.run.map_id === mapId && (e.run.status === "queued" || e.run.status === "running"));
    if (active) return apiError(409, "COURSE_IN_PROGRESS", "이미 짜는 중인 코스가 있습니다", { course_run_id: active.run.id });
    const blocked = creditGate("course"); // #432 — 게스트 403, 모자라면 402. 모델 전에
    if (blocked) return blocked;
    const run = buildRun(mapId, requestText, routable, excluded);
    run.id = nextId("course");
    chargeCredit("course", run.id);
    run.status = "queued";
    store.courseRuns[run.id] = { run, requested_by: ME_USER_ID, polls: 0, snapshot_version: scheduleVersion(mapId) };
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
