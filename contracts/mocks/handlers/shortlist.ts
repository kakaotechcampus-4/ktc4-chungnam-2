import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type Route } from "../store";
import { apiError, shortlistPermissions } from "../util";

function haversineApproxMeters(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  // 13절: 직선거리(PostGIS) 근사. 목 서버용 단순 유클리드 근사.
  const dLat = (a.lat - b.lat) * 111_000;
  const dLng = (a.lng - b.lng) * 88_000;
  return Math.sqrt(dLat * dLat + dLng * dLng);
}

export const shortlistHandlers = [
  http.get("*/maps/:mapId/shortlist", ({ params }) => {
    const mapId = params.mapId as string;
    const items = store.shortlist[mapId] ?? [];
    return HttpResponse.json(items.map((i) => ({ ...i, permissions: shortlistPermissions(i) })));
  }),

  http.post("*/maps/:mapId/shortlist", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const body = (await request.json()) as { pin_id: string };
    const pin = store.pins[body.pin_id];
    if (!pin) return apiError(404, "PIN_NOT_FOUND", "핀을 찾을 수 없습니다");
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

  http.get("*/maps/:mapId/route", ({ params }) => {
    const mapId = params.mapId as string;
    const items = store.shortlist[mapId] ?? [];
    if (items.length < 2) return HttpResponse.json([]);
    // 5-10: 최근접 이웃 기반 순수 계산. 지역 클러스터링은 목 서버에서 단일 지역으로 단순화한다.
    const pins = items.map((i) => i.pin).filter(Boolean) as NonNullable<(typeof items)[number]["pin"]>[];
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
    return HttpResponse.json([route]);
  }),
];
