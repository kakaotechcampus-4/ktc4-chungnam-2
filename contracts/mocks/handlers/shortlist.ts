import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type Route, type ShortlistItem } from "../store";
import { apiError, shortlistPermissions } from "../util";

function haversineApproxMeters(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  // 13절: 직선거리(PostGIS) 근사. 목 서버용 단순 유클리드 근사.
  const dLat = (a.lat - b.lat) * 111_000;
  const dLng = (a.lng - b.lng) * 88_000;
  return Math.sqrt(dLat * dLat + dLng * dLng);
}

const csvCell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);

/** 확정 리스트 한 줄(#471). live 핀은 이름을 모르므로 검색어 + "(이름 확인 필요)", 링크는 카카오 장소 페이지. */
function exportRow(i: ShortlistItem, n: number) {
  const pin = i.pin;
  const live = pin.source === "live";
  const name = live ? `${pin.search_query ?? ""} (이름 확인 필요)` : (pin.place_name ?? "");
  const link = live && pin.kakao_place_id ? `https://place.map.kakao.com/${pin.kakao_place_id.replace(/^kakao:/, "")}` : (pin.place_url ?? "");
  return [String(n), name, pin.category, link, pin.memo ?? ""];
}

type ScheduledItem = ShortlistItem & { scheduled_date?: string | null };
function sortedSchedule(mapId: string) {
  const items = (store.shortlist[mapId] ?? []) as ScheduledItem[];
  return [...items].sort((a, b) => (a.scheduled_date ?? "9999").localeCompare(b.scheduled_date ?? "9999") || (a.visit_order ?? 1e9) - (b.visit_order ?? 1e9));
}
/** 일정 version — 장소 집합·날짜·순서·여행 기간이 들어 있다. AI 코스가 요청 때 저장하고 stale 판정에 쓴다(#1237). */
export function scheduleVersion(mapId: string) {
  const map = store.maps[mapId];
  return JSON.stringify([map.start_date, map.end_date, sortedSchedule(mapId).map(i => [i.id, i.scheduled_date ?? null, i.visit_order ?? null])]);
}
function scheduleSnapshot(mapId: string) {
  const map = store.maps[mapId];
  const sorted = sortedSchedule(mapId);
  const version = scheduleVersion(mapId);
  return { start_date: map.start_date, end_date: map.end_date, version, items: sorted.map(i => ({ ...i, scheduled_date: i.scheduled_date ?? null, permissions: shortlistPermissions(i) })) };
}

export const shortlistHandlers = [
  http.get("*/maps/:mapId/shortlist/schedule", ({ params }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(scheduleSnapshot(mapId));
  }),
  http.put("*/maps/:mapId/shortlist/schedule", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const map = store.maps[mapId];
    if (!map) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const body = await request.json() as { version: string; groups: { date: string | null; item_ids: string[] }[] };
    if (body.version !== scheduleSnapshot(mapId).version) return apiError(409, "SHORTLIST_STALE", "확정 리스트가 변경되었습니다");
    const items = (store.shortlist[mapId] ?? []) as ScheduledItem[];
    const ids = body.groups.flatMap(g => g.item_ids);
    const dates = body.groups.map(g => g.date);
    if (new Set(dates).size !== dates.length || dates.some(d => d !== null && (d < map.start_date || d > map.end_date)) || ids.length !== items.length || new Set(ids).size !== ids.length || ids.some(id => !items.some(i => i.id === id))) return apiError(422, "VALIDATION_ERROR", "일정이 유효하지 않습니다");
    for (const group of body.groups) group.item_ids.forEach((id, index) => { const item = items.find(i => i.id === id)!; item.scheduled_date = group.date; item.visit_order = index; });
    return HttpResponse.json(scheduleSnapshot(mapId));
  }),

  // #471 확정 리스트 내보내기 — 확정 순서대로. 응답은 JSON이 아니라 파일이다.
  http.get("*/maps/:mapId/shortlist/export", ({ params, request }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const format = new URL(request.url).searchParams.get("format") ?? "txt";
    if (format !== "txt" && format !== "csv") return apiError(422, "VALIDATION_ERROR", "format은 txt 또는 csv");
    const items = scheduleSnapshot(mapId).items;
    let previous: string | null | undefined = undefined;
    let order = 0;
    const rows = items.map(i => {
      if (i.scheduled_date !== previous) { previous = i.scheduled_date; order = 0; }
      return [i.scheduled_date ?? "미배정", ...exportRow(i, ++order)];
    });
    if (format === "csv") {
      const body = "\uFEFF" + [["날짜", "순서", "이름", "분류", "링크", "메모"], ...rows].map((r) => r.map(csvCell).join(",")).join("\r\n") + "\r\n";
      return new HttpResponse(body, { headers: { "Content-Type": "text/csv; charset=utf-8", "Content-Disposition": "attachment; filename*=UTF-8''shortlist.csv" } });
    }
    const body = rows.length === 0 ? "확정한 장소가 아직 없어요\n" : rows.map((r, idx) => `${idx === 0 || rows[idx - 1][0] !== r[0] ? `[${r[0]}]\n` : ""}${r[1]}. ${r[2]} (${r[3]})${r[4] ? ` ${r[4]}` : ""}${r[5] ? ` — ${r[5]}` : ""}`).join("\n") + "\n";
    return new HttpResponse(body, { headers: { "Content-Type": "text/plain; charset=utf-8", "Content-Disposition": "attachment; filename*=UTF-8''shortlist.txt" } });
  }),

  http.get("*/maps/:mapId/shortlist", ({ params }) => {
    const mapId = params.mapId as string;
    const items = store.shortlist[mapId] ?? [];
    return HttpResponse.json(items.map((i) => ({ ...i, permissions: shortlistPermissions(i) })));
  }),

  http.post("*/maps/:mapId/shortlist", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const body = (await request.json()) as { pin_id: string };
    const pin = store.pins[body.pin_id];
    if (!pin) return apiError(404, "NOT_FOUND", "핀을 찾을 수 없습니다");
    pin.kind = "확정"; // 5-2: 확정이 원래 종류를 덮어쓴다
    const itemId = nextId("shortlist");
    const items = store.shortlist[mapId] ?? (store.shortlist[mapId] = []);
    const item = { id: itemId, pin, visit_order: items.length, added_by: ME_USER_ID, permissions: { can_remove_from_shortlist: true } };
    items.push(item);
    const map = store.maps[mapId];
    if (map) map.confirmed_count = items.length;
    return HttpResponse.json(item, { status: 201 });
  }),

  http.delete("*/shortlist/:itemId", ({ params }) => {
    const itemId = params.itemId as string;
    for (const [mapId, items] of Object.entries(store.shortlist)) {
      const idx = items.findIndex((i) => i.id === itemId);
      if (idx >= 0) {
        const [removed] = items.splice(idx, 1);
        if (removed.pin) removed.pin.kind = "일반"; // 단순화: 원래 종류 복원(실제로는 origin 기준, 5-2 참고)
        const map = store.maps[mapId];
        if (map) map.confirmed_count = items.length;
        return new HttpResponse(null, { status: 204 });
      }
    }
    return apiError(404, "SHORTLIST_ITEM_NOT_FOUND", "확정 항목을 찾을 수 없습니다");
  }),

  http.put("*/maps/:mapId/shortlist/order", async ({ params, request }) => {
    // #30: 보기 좋게 순서만 바꾸는 것 — 동선과는 무관, 재계산을 트리거하지 않는다.
    const mapId = params.mapId as string;
    const body = (await request.json()) as { item_ids: string[] };
    const items = store.shortlist[mapId] ?? [];
    if ((items as ScheduledItem[]).some(i => i.scheduled_date)) return apiError(409, "SHORTLIST_SCHEDULED", "날짜별 일정을 사용 중입니다");
    const byId = new Map(items.map((i) => [i.id, i]));
    body.item_ids.forEach((id, idx) => {
      const item = byId.get(id);
      if (item) item.visit_order = idx;
    });
    items.sort((a, b) => (a.visit_order ?? 0) - (b.visit_order ?? 0));
    return HttpResponse.json(items.map((i) => ({ ...i, permissions: shortlistPermissions(i) })));
  }),

  http.get("*/maps/:mapId/route", ({ params }) => {
    // 마지막으로 계산된 동선만 반환한다 — 여기서 재계산하지 않는다 (#30)
    const mapId = params.mapId as string;
    return HttpResponse.json(store.routes[mapId] ?? []);
  }),

  http.post("*/maps/:mapId/route", ({ params }) => {
    // 「동선 짜주기」 — 사람이 눌러야만 실행된다 (#30)
    const mapId = params.mapId as string;
    const items = store.shortlist[mapId] ?? [];
    const routes = calculateRoutes(items);
    store.routes[mapId] = routes;
    return HttpResponse.json(routes);
  }),
];

function calculateRoutes(items: ShortlistItem[]): Route[] {
  // 5-10: 최근접 이웃 기반 순수 계산. 지역 클러스터링은 목 서버에서 단일 지역으로 단순화한다.
  // #382: 좌표가 없는 실시간 핀(source=live)은 서버가 위치를 몰라 동선에서 빠진다.
  const pins = items
    .map((i) => i.pin)
    .filter((p): p is NonNullable<typeof p> => !!p && p.lat !== undefined && p.lng !== undefined);
  if (pins.length < 2) return [];
  const legs: Route["legs"] = [];
  let total = 0;
  for (let i = 0; i < pins.length - 1; i++) {
    const a = pins[i]!;
    const b = pins[i + 1]!;
    const dist = haversineApproxMeters({ lat: a.lat ?? 0, lng: a.lng ?? 0 }, { lat: b.lat ?? 0, lng: b.lng ?? 0 });
    total += dist;
    legs.push({ from_pin_id: a.id, to_pin_id: b.id, distance_m: Math.round(dist), approx_minutes: Math.max(1, Math.round(dist / 67)) });
  }
  const route: Route = {
    region_label: "제주시 권역",
    ordered_pin_ids: pins.map((p) => p.id!).filter(Boolean) as string[],
    total_distance_m: Math.round(total),
    legs,
  };
  return [route];
}
