import { http, HttpResponse } from "msw";
import { ME_USER_ID, emitEvent, nextId, store, type Pin } from "../store";
import { apiError, pinPermissions } from "../util";
import { SEED_PLACES } from "./places";

function visiblePins(mapId: string): Pin[] {
  return Object.values(store.pins).filter((p) => {
    // v1의 핀은 모두 public이다(#273). 비공개 AI 후보는 핀이 아니라 store.candidates에 있다.
    return p.map_id === mapId;
  });
}

export const pinsHandlers = [
  http.get("*/maps/:mapId/pins", ({ params, request }) => {
    const mapId = params.mapId as string;
    const url = new URL(request.url);
    const category = url.searchParams.get("category");
    const kind = url.searchParams.get("kind");
    const createdBy = url.searchParams.getAll("created_by");
    let pins = visiblePins(mapId);
    if (category) pins = pins.filter((p) => p.category === category);
    if (kind) pins = pins.filter((p) => p.kind === kind);
    if (createdBy.length) pins = pins.filter((p) => p.created_by && createdBy.includes(p.created_by)); // #26
    return HttpResponse.json(
      pins.map((p) => ({
        ...p,
        permissions: pinPermissions(p),
        my_reaction: (store.reactions[p.id] ?? []).find((r) => r.user_id === ME_USER_ID) ?? null,
      })),
    );
  }),

  http.get("*/pins/:pinId/reactions", ({ params }) => {
    const pinId = params.pinId as string;
    if (!store.pins[pinId]) return apiError(404, "NOT_FOUND", "핀을 찾을 수 없습니다");
    const list = store.reactions[pinId] ?? [];
    return HttpResponse.json(
      list.map((r) => ({ ...r, display_name: store.members[store.pins[pinId].map_id]?.find((m) => m.user_id === r.user_id)?.display_name ?? "구성원" })),
    );
  }),

  http.post("*/maps/:mapId/pins", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const body = (await request.json()) as {
      category: Pin["category"];
      source?: "link" | "search" | "coordinate";
      link_url?: string;
      place_id?: string;
      place_name?: string;
      lat?: number;
      lng?: number;
    };
    // #191(2026-10-01): v1의 핀은 모두 자체 DB 장소를 가리킨다. 목 서버는 GET /places/search의 시드 장소(kakao:mock-*)를
    // "자체 DB에 짝이 있는 장소"로 본다. 요청의 place_name·lat·lng는 매칭 힌트라 쓰지 않는다.
    if (body.source === "link" || body.link_url) {
      return apiError(422, "VALIDATION_ERROR", "링크로는 핀을 찍을 수 없어요. 이름으로 검색해 주세요");
    }
    if (body.source === "coordinate" || !body.place_id || !body.place_name || body.lat === undefined || body.lng === undefined) {
      return apiError(422, "VALIDATION_ERROR", "지도를 눌러 핀을 찍을 수는 없어요. 장소를 검색해서 골라 주세요");
    }
    const own = SEED_PLACES.find((p) => p.place_id === body.place_id);
    // 자체 DB는 음식점·카페·관광지만 담는다(TourAPI 숙박 제외, 2026-10-01) — 숙소·기타는 핀으로 만들 수 없다
    if (!own || own.category === "숙소" || own.category === "기타") {
      return apiError(422, "PLACE_NOT_SUPPORTED", "아직 지원하지 않는 장소예요");
    }
    if (own.category && body.category !== own.category) {
      return apiError(422, "VALIDATION_ERROR", `이 장소의 분류는 ${own.category}예요`);
    }
    // 가드레일 6 / 중복 판정: 이 목 서버는 (mapId, 장소) 동일 기준으로만 임시 판정한다.
    const dup = Object.values(store.pins).find((p) => p.map_id === mapId && (p as any)._place_id === own.place_id);
    if (dup) return apiError(409, "PIN_DUPLICATE", "이미 지도에 있는 장소예요", { pin_id: dup.id });
    const pinId = nextId("pin");
    const pin: Pin = {
      id: pinId,
      map_id: mapId,
      category: body.category,
      kind: "일반",
      visibility: "public",
      lat: own.lat,
      lng: own.lng,
      place_name: own.place_name,
      ...(own.place_source?.url ? { place_url: own.place_source.url } : {}),
      created_by: ME_USER_ID,
      created_by_display_name: store.users[ME_USER_ID]?.display_name ?? "나",
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 0, neutral: 0, against: 0 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true },
    };
    (pin as any)._place_id = own.place_id;
    store.pins[pinId] = pin;
    store.reactions[pinId] = [];
    emitEvent(mapId, "public", "pin.created", pin); // docs/events.md — private 핀은 여기 안 온다(지금 목 서버는 항상 public으로만 생성)
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
    const pin = store.pins[pinId];
    if (!pin) return apiError(404, "NOT_FOUND", "핀을 찾을 수 없습니다");
    delete store.pins[pinId];
    delete store.reactions[pinId];
    emitEvent(pin.map_id, "public", "pin.deleted", { pin_id: pinId });
    return new HttpResponse(null, { status: 204 });
  }),

  http.put("*/pins/:pinId/reaction", async ({ params, request }) => {
    const pinId = params.pinId as string;
    const pin = store.pins[pinId];
    if (!pin) return apiError(404, "NOT_FOUND", "핀을 찾을 수 없습니다");
    if (pin.category === "숙소") return apiError(422, "REACTION_NOT_ALLOWED", "숙소에는 반응을 남길 수 없어요");
    const body = (await request.json()) as { type: "like" | "neutral" | "against"; reason_text?: string; reason_chip_ids?: string[] };
    if (body.type === "against" && !body.reason_text && !(body.reason_chip_ids && body.reason_chip_ids.length)) {
      return apiError(422, "EVIDENCE_REQUIRED", "반대에는 사유가 필요해요");
    }
    const list = store.reactions[pinId] ?? (store.reactions[pinId] = []);
    const idx = list.findIndex((r) => r.user_id === ME_USER_ID);
    const reaction = {
      pin_id: pinId,
      user_id: ME_USER_ID,
      type: body.type,
      reason_text: body.reason_text ?? "",
      reason_chip_ids: body.reason_chip_ids ?? [],
    };
    if (idx >= 0) list[idx] = reaction;
    else list.push(reaction);
    // 요약 재계산
    pin.reaction_summary = {
      like: list.filter((r) => r.type === "like").length,
      neutral: list.filter((r) => r.type === "neutral").length,
      against: list.filter((r) => r.type === "against").length,
    };
    emitEvent(pin.map_id, "public", "reaction.changed", { pin_id: pinId, reaction_summary: pin.reaction_summary });
    return HttpResponse.json(reaction);
  }),

  http.delete("*/pins/:pinId/reaction", ({ params }) => {
    const pinId = params.pinId as string;
    const pin = store.pins[pinId];
    if (!pin) return apiError(404, "NOT_FOUND", "핀을 찾을 수 없습니다");
    const list = store.reactions[pinId] ?? [];
    store.reactions[pinId] = list.filter((r) => r.user_id !== ME_USER_ID);
    pin.reaction_summary = {
      like: store.reactions[pinId].filter((r) => r.type === "like").length,
      neutral: store.reactions[pinId].filter((r) => r.type === "neutral").length,
      against: store.reactions[pinId].filter((r) => r.type === "against").length,
    };
    emitEvent(pin.map_id, "public", "reaction.changed", { pin_id: pinId, reaction_summary: pin.reaction_summary });
    return new HttpResponse(null, { status: 204 });
  }),
];
