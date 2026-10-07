import { http, HttpResponse } from "msw";
import { ME_USER_ID, emitEvent, nextId, store, type Pin } from "../store";
import { apiError, pinPermissions } from "../util";
import { SEED_PLACES } from "./places";
import { CATEGORY_RULES } from "../categories";
import { chipsFor } from "../chips";

/** reaction.changed 에 싣는 "남긴 사람"(docs/events.md). 목 서버는 단일 사용자라 나다. */
const actor = (mapId: string) => ({
  user_id: ME_USER_ID,
  display_name: store.members[mapId]?.find((m) => m.user_id === ME_USER_ID)?.display_name ?? "구성원",
});

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
      source?: "link" | "search" | "coordinate" | "live";
      link_url?: string;
      kakao_place_id?: string;
      search_query?: string;
      memo?: string;
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
    // #382 실시간 핀 — 자체 DB에 없는 장소. 카카오 장소 ID·검색어·메모·카테고리만 받고 이름·좌표는 받지도 돌려주지도 않는다.
    if (body.source === "live") {
      if (!body.kakao_place_id || !body.search_query?.trim()) {
        return apiError(422, "VALIDATION_ERROR", "장소 ID와 검색어가 필요해요");
      }
      if (!CATEGORY_RULES[body.category]?.pinnable) {
        return apiError(422, "VALIDATION_ERROR", `${body.category}은(는) 핀으로 남길 수 없어요`);
      }
      const dupLive = Object.values(store.pins).find((p) => p.map_id === mapId && p.kakao_place_id === body.kakao_place_id);
      if (dupLive) return apiError(409, "PIN_DUPLICATE", "이미 지도에 있는 장소예요", { pin_id: dupLive.id });
      const liveId = nextId("pin");
      const livePin: Pin = {
        id: liveId,
        map_id: mapId,
        category: body.category,
        kind: "일반",
        visibility: "public",
        source: "live",
        kakao_place_id: body.kakao_place_id,
        search_query: body.search_query.trim(),
        ...(body.memo ? { memo: body.memo } : {}),
        created_by: ME_USER_ID,
        created_by_display_name: store.users[ME_USER_ID]?.display_name ?? "나",
        created_at: new Date().toISOString(),
        checks: [],
        source_run_id: null,
        reaction_summary: { like: 0, against: 0 },
        permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true },
      };
      store.pins[liveId] = livePin;
      store.reactions[liveId] = [];
      emitEvent(mapId, "public", "pin.created", livePin);
      return HttpResponse.json(livePin, { status: 201 });
    }
    if (body.source === "coordinate" || !body.place_id || !body.place_name || body.lat === undefined || body.lng === undefined) {
      return apiError(422, "VALIDATION_ERROR", "지도를 눌러 핀을 찍을 수는 없어요. 장소를 검색해서 골라 주세요");
    }
    const own = SEED_PLACES.find((p) => p.place_id === body.place_id);
    // 자체 DB는 pinnable 카테고리(음식점·카페·관광지)만 담는다(TourAPI 숙박 제외, 2026-10-01) — 숙소·기타는 핀으로 만들 수 없다
    if (!own || (own.category && !CATEGORY_RULES[own.category].pinnable)) {
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
      source: "db",
      lat: own.lat,
      lng: own.lng,
      place_name: own.place_name,
      ...(own.place_source?.url ? { place_url: own.place_source.url } : {}),
      created_by: ME_USER_ID,
      created_by_display_name: store.users[ME_USER_ID]?.display_name ?? "나",
      created_at: new Date().toISOString(),
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 0, against: 0 },
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
    // 반응을 하나라도 남긴 구성원 수 — 이 지도의 핀 중 하나라도 반응한 사람(탈퇴자는 members에 없어 자연히 빠진다)
    const memberIds = new Set((store.members[mapId] ?? []).map((m) => m.user_id));
    const reacted = new Set(
      Object.values(store.pins)
        .filter((p) => p.map_id === mapId)
        .flatMap((p) => (store.reactions[p.id] ?? []).map((r) => r.user_id))
        .filter((id) => memberIds.has(id)),
    );
    return HttpResponse.json({ by_category, by_kind, members_with_opinion: reacted.size, members_total: memberIds.size });
  }),

  // #60: 반대 사유 칩 — 고정 목록(docs/constraints.md「반대 사유 칩」)
  http.get("*/categories/:category/reason-chips", ({ params }) => HttpResponse.json(chipsFor(decodeURIComponent(params.category as string)))),

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
    if (!CATEGORY_RULES[pin.category].reactable) return apiError(422, "REACTION_NOT_ALLOWED", `${pin.category}에는 반응을 남길 수 없어요`);
    const body = (await request.json()) as { type: "like" | "against"; reason_text?: string; reason_chip_ids?: string[] };
    if (body.type !== "like" && body.type !== "against") {
      return apiError(422, "VALIDATION_ERROR", "반응은 좋음(like)과 반대(against)만 남길 수 있어요"); // 2026-10-07 #360: neutral(△) 폐지
    }
    if (body.type === "against" && !body.reason_text && !(body.reason_chip_ids && body.reason_chip_ids.length)) {
      return apiError(422, "EVIDENCE_REQUIRED", "반대에는 사유가 필요해요");
    }
    // #60: 칩은 그 핀의 카테고리 목록에 있는 id여야 한다(이름을 그대로 보내면 422)
    const allowed = new Set(chipsFor(pin.category).map((c) => c.id));
    const unknownChip = (body.reason_chip_ids ?? []).find((id) => !allowed.has(id));
    if (unknownChip) return apiError(422, "VALIDATION_ERROR", "알 수 없는 사유 칩이에요", { reason_chip_id: unknownChip });
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
      against: list.filter((r) => r.type === "against").length,
    };
    emitEvent(pin.map_id, "public", "reaction.changed", { pin_id: pinId, reaction_summary: pin.reaction_summary, ...actor(pin.map_id), type: body.type });
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
      against: store.reactions[pinId].filter((r) => r.type === "against").length,
    };
    emitEvent(pin.map_id, "public", "reaction.changed", { pin_id: pinId, reaction_summary: pin.reaction_summary, ...actor(pin.map_id), type: null });
    return new HttpResponse(null, { status: 204 });
  }),
];
