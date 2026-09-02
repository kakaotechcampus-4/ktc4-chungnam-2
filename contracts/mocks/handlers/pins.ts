import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type Pin } from "../store";
import { apiError, pinPermissions } from "../util";

function visiblePins(mapId: string): Pin[] {
  return Object.values(store.pins).filter((p) => {
    if (p.map_id !== mapId) return false;
    if (p.visibility === "private") {
      // 5-5-1: 요청한 사람에게만 보인다. 목 서버는 항상 ME_USER_ID로 요청한다고 가정한다.
      const runId = p.source_run_id ?? undefined;
      return runId ? store.runRequestedBy[runId] === ME_USER_ID : false;
    }
    return true;
  });
}

export const pinsHandlers = [
  http.get("*/maps/:mapId/pins", ({ params, request }) => {
    const mapId = params.mapId as string;
    const url = new URL(request.url);
    const category = url.searchParams.get("category");
    const kind = url.searchParams.get("kind");
    let pins = visiblePins(mapId);
    if (category) pins = pins.filter((p) => p.category === category);
    if (kind) pins = pins.filter((p) => p.kind === kind);
    return HttpResponse.json(pins.map((p) => ({ ...p, permissions: pinPermissions(p) })));
  }),

  http.post("*/maps/:mapId/pins", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const body = (await request.json()) as {
      category: Pin["category"];
      source?: "link" | "search" | "coordinate";
      link_url?: string;
      place_id?: string;
      lat?: number;
      lng?: number;
    };
    // 가드레일 6 / 중복 판정: 이 목 서버는 (mapId, place_id) 동일 기준으로만 임시 판정한다.
    // 실제 기준은 결정 이슈("중복 핀 '같은 곳' 판정 기준") 확정 후 반영한다.
    if (body.place_id) {
      const dup = Object.values(store.pins).find((p) => p.map_id === mapId && (p as any)._place_id === body.place_id);
      if (dup) return apiError(409, "PIN_DUPLICATE", "이미 지도에 있는 장소예요", { pin_id: dup.id });
    }
    const pinId = nextId("pin");
    const pin: Pin = {
      id: pinId,
      map_id: mapId,
      category: body.category,
      kind: "일반",
      visibility: "public",
      lat: body.lat ?? 33.45,
      lng: body.lng ?? 126.56,
      place_name: "새로 찍은 핀",
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 0, neutral: 0, against: 0 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true },
    };
    (pin as any)._place_id = body.place_id;
    store.pins[pinId] = pin;
    store.reactions[pinId] = [];
    return HttpResponse.json(pin, { status: 201 });
  }),

  http.get("*/maps/:mapId/counts", ({ params }) => {
    const mapId = params.mapId as string;
    const pins = visiblePins(mapId);
    const by_category: Record<string, number> = {};
    const by_kind: Record<string, number> = {};
    for (const p of pins) {
      if (p.category) by_category[p.category] = (by_category[p.category] ?? 0) + 1;
      if (p.kind) by_kind[p.kind] = (by_kind[p.kind] ?? 0) + 1;
    }
    return HttpResponse.json({ by_category, by_kind });
  }),

  http.delete("*/pins/:pinId", ({ params }) => {
    const pinId = params.pinId as string;
    if (!store.pins[pinId]) return apiError(404, "PIN_NOT_FOUND", "핀을 찾을 수 없습니다");
    delete store.pins[pinId];
    delete store.reactions[pinId];
    return new HttpResponse(null, { status: 204 });
  }),

  http.put("*/pins/:pinId/reaction", async ({ params, request }) => {
    const pinId = params.pinId as string;
    const pin = store.pins[pinId];
    if (!pin) return apiError(404, "PIN_NOT_FOUND", "핀을 찾을 수 없습니다");
    const body = (await request.json()) as { type: "like" | "neutral" | "against"; reason_text?: string; reason_chip_ids?: string[] };
    if (body.type === "against" && !body.reason_text && !(body.reason_chip_ids && body.reason_chip_ids.length)) {
      return apiError(422, "EVIDENCE_REQUIRED", "반대에는 사유가 필요해요");
    }
    const list = store.reactions[pinId] ?? (store.reactions[pinId] = []);
    const idx = list.findIndex((r) => r.user_id === ME_USER_ID);
    const reaction = { pin_id: pinId, user_id: ME_USER_ID, type: body.type, reason_text: body.reason_text ?? "" };
    if (idx >= 0) list[idx] = reaction;
    else list.push(reaction);
    // 요약 재계산
    pin.reaction_summary = {
      like: list.filter((r) => r.type === "like").length,
      neutral: list.filter((r) => r.type === "neutral").length,
      against: list.filter((r) => r.type === "against").length,
    };
    return HttpResponse.json(reaction);
  }),

  http.delete("*/pins/:pinId/reaction", ({ params }) => {
    const pinId = params.pinId as string;
    const pin = store.pins[pinId];
    if (!pin) return apiError(404, "PIN_NOT_FOUND", "핀을 찾을 수 없습니다");
    const list = store.reactions[pinId] ?? [];
    store.reactions[pinId] = list.filter((r) => r.user_id !== ME_USER_ID);
    pin.reaction_summary = {
      like: store.reactions[pinId].filter((r) => r.type === "like").length,
      neutral: store.reactions[pinId].filter((r) => r.type === "neutral").length,
      against: store.reactions[pinId].filter((r) => r.type === "against").length,
    };
    return new HttpResponse(null, { status: 204 });
  }),
];
