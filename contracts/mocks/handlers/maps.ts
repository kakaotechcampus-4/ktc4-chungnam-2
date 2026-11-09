import { http, HttpResponse } from "msw";
import { ME_USER_ID, emitEvent, nextId, store, type MapEntity, type MapRegion, type Pin } from "../store";
import { apiError, getMapOr404, pinPermissions } from "../util";

/** 지도 응답의 핀 수는 저장값이 아니라 지금 있는 핀에서 센다(핀을 찍거나 지우면 바로 달라진다). */
const pinCount = (mapId: string) => Object.values(store.pins).filter((p) => p.map_id === mapId && p.visibility === "public").length;
const withPinCount = <T extends { id: string }>(map: T) => ({ ...map, pin_count: pinCount(map.id) });

/** 내 지도 상한(#369, #433에서 10→20). 만들거나 참여한 지도 합산 — 목 서버는 삭제·나간 지도를 이미 지우므로 지금 속한 지도만 센다. */
export const MAP_LIMIT = 20;
export const TRIP_MAX_DAYS = 90; // #1371: 시작일·종료일 포함
const tripDays = (start: string, end: string) => Math.round((Date.parse(end) - Date.parse(start)) / 86400000) + 1;
const tripTooLong = () => apiError(422, "TRIP_TOO_LONG", `여행 기간은 최대 ${TRIP_MAX_DAYS}일까지 정할 수 있어요`, { limit: TRIP_MAX_DAYS });
const lastSeen: Record<string, string> = {};   // #1556 mapId -> 마지막으로 본 때(나)
const myMapCount = () => Object.keys(store.maps).filter((id) => (store.members[id] ?? []).some((m) => m.user_id === ME_USER_ID)).length;
const mapLimitError = () =>
  apiError(409, "MAP_LIMIT", `지도는 ${MAP_LIMIT}개까지 만들거나 참여할 수 있어요. 지도를 나가거나 삭제한 뒤 다시 시도해 주세요`, { limit: MAP_LIMIT, count: myMapCount() });

/** 방장이 나가면 방장이 될 사람(#369). 목 서버의 구성원 배열은 들어온 순서라 나 다음 첫 사람이다(탈퇴자 개념은 없다). */
const successorOf = (mapId: string) => (store.members[mapId] ?? []).find((m) => m.user_id !== ME_USER_ID) ?? null;
const isOwner = (mapId: string) => (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID && m.role === "owner");

/** 지도 대표 이미지(#1445) — 실서버 maps.core와 같은 값. 422 COVER_INVALID의 detail로 내려 준다. */
export const COVER_MAX_BYTES = 512 * 1024;
export const COVER_TYPES = ["image/webp", "image/jpeg", "image/png"] as const;
const coverInvalid = () =>
  apiError(422, "COVER_INVALID", "올릴 수 없는 대표 이미지예요", { limit_bytes: COVER_MAX_BYTES, types: [...COVER_TYPES] });
/** 앞 바이트가 그 형식인지(이름표만 바꾼 파일을 막는다). */
function looksLike(type: string, bytes: Uint8Array) {
  const at = (offset: number, sig: number[]) => sig.every((b, i) => bytes[offset + i] === b);
  if (type === "image/webp") return at(0, [0x52, 0x49, 0x46, 0x46]) && at(8, [0x57, 0x45, 0x42, 0x50]);
  if (type === "image/jpeg") return at(0, [0xff, 0xd8, 0xff]);
  if (type === "image/png") return at(0, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  return false;
}
const coverUrl = (mapId: string) => {
  const cover = store.mapCovers[mapId];
  return cover ? `/maps/${mapId}/cover?v=${cover.updated_at}` : undefined;
};
/** 방장이 아니면 403, 구성원이 아니면 404 응답. 통과하면 null. */
function ownerGate(mapId: string) {
  if (!getMapOr404(mapId) || !(store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
  if (!isOwner(mapId)) return apiError(403, "FORBIDDEN", "방장만 바꿀 수 있어요");
  return null;
}

/** 복사본 제목(#1446) — 실서버 maps.core.copy_title과 같은 규칙. 끝의 「 (k)」를 떼고, 내 지도에 없는 가장 작은 n으로 「제목 (n)」. 100자 안. */
export function copyTitle(source: string, taken: Set<string>) {
  // 서버(파이썬 str)처럼 코드 포인트 단위로 자르고, \d처럼 유니코드 숫자도 숫자로 본다 — 이모지·전각 숫자에서 결과가 갈리지 않게.
  const base = Array.from(source.replace(/ \((\p{Nd}+)\)$/u, ""));
  for (let n = 1; ; n += 1) {
    const suffix = ` (${n})`;
    const title = base.slice(0, 100 - suffix.length).join("").trimEnd() + suffix;
    if (!taken.has(title)) return title;
  }
}

/** 지도 응답 — 핀 수와 요청자(나) 기준 permissions를 붙이고, 상세에서만 next_owner를 채운다(#369). */
function toMapResponse(map: MapEntity, { detail = false } = {}) {
  const owner = isOwner(map.id);
  const next = owner ? successorOf(map.id) : null;
  const { created_by: createdBy, ...rest } = map;
  const ownerName = (store.members[map.id] ?? []).find((m) => m.role === "owner")?.display_name;
  const cover = coverUrl(map.id);
  return {
    ...withPinCount(rest),
    ...(cover ? { cover_url: cover } : {}), // #1445: 올린 이미지가 없으면 키가 없다
    ...(ownerName ? { owner_display_name: ownerName } : {}), // #1445: 초대받은 지도 카드의 「○○님의 지도」
    my_role: owner ? ("owner" as const) : ("member" as const),
    created_by_me: createdBy === ME_USER_ID, // #340·회의 14번: 만든 사람이 위임해도 값은 그대로다(my_role과 달라질 수 있다)
    permissions: { can_delete: owner, can_leave: !owner || next !== null, can_edit: owner, can_manage_invites: owner, can_transfer_owner: owner, can_copy: owner },
    ...(detail && next ? { next_owner: { user_id: next.user_id!, display_name: next.display_name ?? "" } } : {}),
  };
}

/** 쓸 수 없는 초대 토큰이면 응답을 돌려준다(#467). 끈 링크는 410 INVITE_REVOKED, 만료는 410 INVITE_EXPIRED. */
function inviteGone(invite: { expires_at: string; revoked?: boolean }) {
  if (invite.revoked) return apiError(410, "INVITE_REVOKED", "방장이 이 초대 링크를 껐어요. 새 링크를 요청하세요");
  if (new Date(invite.expires_at).getTime() < Date.now()) return apiError(410, "INVITE_EXPIRED", "초대 링크가 만료됐어요");
  return null;
}

export const mapsHandlers = [
  // #24: 로그인 직후 진입점 — 내가 구성원인 지도만, 최근 생성순(store.maps는 생성 순서대로
  // 키가 쌓이므로 reverse()면 충분하다). 속한 지도가 없으면 빈 배열.
  http.get("*/maps", () => {
    const mine = Object.entries(store.maps)
      .filter(([mapId]) => (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID))
      .map(([, map]) => toMapResponse(map))
      .reverse();
    return HttpResponse.json({ items: mine, limit: MAP_LIMIT, trip_max_days: TRIP_MAX_DAYS }); // #623, #1371: 목록과 상한을 함께
  }),

  // #464 내가 방장인 삭제된 지도 — 30일 안인 것만, 최근 삭제순
  http.get("*/maps/trash", () => {
    const retention = 30 * 86400000;
    const items = Object.entries(store.trashedMaps)
      .filter(([, t]) => t.members.some((m) => m.user_id === ME_USER_ID && m.role === "owner") && Date.now() - new Date(t.deleted_at).getTime() < retention)
      .map(([id, t]) => {
        const purgeAt = new Date(new Date(t.deleted_at).getTime() + retention);
        return {
          id, title: t.map.title, start_date: t.map.start_date, end_date: t.map.end_date, region: t.map.region,
          member_count: t.members.length, deleted_at: t.deleted_at, purge_at: purgeAt.toISOString(),
          days_left: Math.max(0, Math.ceil((purgeAt.getTime() - Date.now()) / 86400000)),
        };
      })
      .sort((a, b) => b.deleted_at.localeCompare(a.deleted_at));
    return HttpResponse.json({ items, retention_days: 30 });
  }),

  http.post("*/maps", async ({ request }) => {
    const body = (await request.json()) as {
      title: string; start_date: string; end_date: string; region?: MapRegion;
    };
    if (store.users[ME_USER_ID]?.is_guest) return apiError(403, "GUEST_NOT_ALLOWED", "지도를 만들려면 카카오로 로그인해 주세요"); // #472
    if (body.start_date && body.end_date && body.end_date < body.start_date) return apiError(422, "VALIDATION_ERROR", "종료일은 시작일과 같거나 뒤여야 해요"); // #1197
    if (body.start_date && body.end_date && tripDays(body.start_date, body.end_date) > TRIP_MAX_DAYS) return tripTooLong(); // #1371
    if (myMapCount() >= MAP_LIMIT) return mapLimitError();
    const mapId = nextId("map");
    store.maps[mapId] = {
      id: mapId,
      title: body.title,
      start_date: body.start_date,
      end_date: body.end_date,
      region: body.region,
      member_count: 1,
      pin_count: 0,
      confirmed_count: 0,
      created_by: ME_USER_ID,
    };
    store.members[mapId] = [{ user_id: ME_USER_ID, role: "owner", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true, is_guest: false }];
    store.shortlist[mapId] = [];
    // architecture.md 3절: 지도 생성 시 프리시딩 잡을 큐잉한다 — 목 서버에서는 즉시 "완료된 것처럼" 취급.
    // 지역(#22)이 있으면 그걸로, 없으면 첫 핀 좌표로 확정한다는 트리거 자체는 목 서버가 흉내낼
    // 필요가 없다(프리시딩은 백엔드 전용 부수효과라 FE가 관찰할 응답이 없다).
    return HttpResponse.json(toMapResponse(store.maps[mapId]), { status: 201 });
  }),

  http.get("*/maps/:mapId", ({ params }) => {
    const map = getMapOr404(params.mapId as string);
    if (!map) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(toMapResponse(map, { detail: true }));
  }),

  // #465 지도 수정 — 방장만. 보낸 필드만 바꾸고, 합친 결과로 검증한다. 지역은 바꾸기만 된다.
  http.patch("*/maps/:mapId", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const map = getMapOr404(mapId);
    if (!map || !(store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    if (!isOwner(mapId)) return apiError(403, "FORBIDDEN", "방장만 지도를 수정할 수 있어요");
    const body = (await request.json()) as { title?: string; start_date?: string; end_date?: string; region?: MapRegion; color?: string | null };
    const title = body.title ?? map.title;
    const start = body.start_date ?? map.start_date;
    const end = body.end_date ?? map.end_date;
    // #1445: color만 null(색 지우기)을 받는다. 다른 필드의 null은 422(실서버와 같다)
    const nulled = Object.entries(body).some(([key, value]) => value === null && key !== "color");
    const badColor = body.color !== undefined && body.color !== null && !/^#[0-9A-Fa-f]{6}$/.test(body.color);
    if (Object.keys(body).length === 0 || nulled || badColor || title.trim().length < 1 || title.length > 100 || end < start) {
      return apiError(422, "VALIDATION_ERROR", "지도 수정 값이 올바르지 않아요");
    }
    if ((body.start_date !== undefined || body.end_date !== undefined) && tripDays(start, end) > TRIP_MAX_DAYS) return tripTooLong(); // #1371: 날짜를 바꿀 때만
    const items = store.shortlist[mapId] ?? [];
    const ordered = [...items].sort((a, b) => (a.scheduled_date ?? "9999").localeCompare(b.scheduled_date ?? "9999") || (a.visit_order ?? 1e9) - (b.visit_order ?? 1e9));
    const unassigned = ordered.filter(i => !i.scheduled_date);
    const outside = ordered.filter(i => i.scheduled_date && (i.scheduled_date < start || i.scheduled_date > end));
    if (outside.length) [...unassigned, ...outside].forEach((item, index) => { item.scheduled_date = null; item.visit_order = index; });
    Object.assign(map, { title, start_date: start, end_date: end, ...(body.region ? { region: body.region } : {}) });
    if (body.color === null) delete map.color;
    else if (body.color !== undefined) map.color = body.color;
    emitEvent(mapId, "public", "map.updated", {
      map_id: mapId, title, start_date: start, end_date: end, ...(map.region ? { region: map.region } : {}),
    });
    return HttpResponse.json(toMapResponse(map, { detail: true }));
  }),

  // #1445 지도 대표 이미지 — 올리기·지우기는 방장만, 받기는 구성원 누구나. 바이트는 메모리에 둔다.
  http.put("*/maps/:mapId/cover", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const gate = ownerGate(mapId);
    if (gate) return gate;
    const type = (request.headers.get("content-type") ?? "").split(";")[0].trim().toLowerCase();
    const data = await request.arrayBuffer();
    if (!(COVER_TYPES as readonly string[]).includes(type) || data.byteLength > COVER_MAX_BYTES || !looksLike(type, new Uint8Array(data))) return coverInvalid();
    const previous = store.mapCovers[mapId]?.updated_at ?? 0;
    store.mapCovers[mapId] = { data, content_type: type, updated_at: Math.max(Math.floor(Date.now() / 1000), previous + 1) }; // 바꾸면 v가 꼭 바뀐다
    return HttpResponse.json(toMapResponse(store.maps[mapId], { detail: true }));
  }),

  http.delete("*/maps/:mapId/cover", ({ params }) => {
    const mapId = params.mapId as string;
    const gate = ownerGate(mapId);
    if (gate) return gate;
    delete store.mapCovers[mapId];
    return HttpResponse.json(toMapResponse(store.maps[mapId], { detail: true }));
  }),

  http.get("*/maps/:mapId/cover", ({ params }) => {
    const mapId = params.mapId as string;
    const cover = store.mapCovers[mapId];
    if (!getMapOr404(mapId) || !(store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID) || !cover) return apiError(404, "NOT_FOUND", "대표 이미지가 없어요");
    return new HttpResponse(cover.data, {
      headers: { "Content-Type": cover.content_type, "Cache-Control": "private, max-age=31536000, immutable" },
    });
  }),

  // #468 방장 직접 넘기기 — 방장만. 대상은 지금 구성원이고 나 자신이 아니다. 나는 구성원으로 남는다.
  http.post("*/maps/:mapId/owner", async ({ params, request }) => {
    const mapId = params.mapId as string;
    const map = getMapOr404(mapId);
    const members = store.members[mapId] ?? [];
    if (!map || !members.some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    if (!isOwner(mapId)) return apiError(403, "FORBIDDEN", "방장만 방장을 넘길 수 있어요");
    const { user_id: to } = (await request.json()) as { user_id: string };
    const target = members.find((m) => m.user_id === to);
    if (!target || to === ME_USER_ID) return apiError(422, "OWNER_TARGET_INVALID", "방장을 넘길 수 없는 사람이에요");
    members.forEach((m) => { if (m.user_id === ME_USER_ID) m.role = "member"; });
    target.role = "owner";
    emitEvent(mapId, "public", "owner.changed", { map_id: mapId, from_user_id: ME_USER_ID, to_user_id: to });
    return HttpResponse.json(toMapResponse(map, { detail: true }));
  }),

  // #369 지도 삭제 — 방장만. 실서버는 soft delete지만 목 서버는 그냥 지운다(이후 모든 조회가 404, 초대 토큰도 404).
  http.delete("*/maps/:mapId", ({ params }) => {
    const mapId = params.mapId as string;
    const mine = (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID);
    if (!getMapOr404(mapId) || !mine) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    if (!isOwner(mapId)) return apiError(403, "FORBIDDEN", "방장만 지도를 삭제할 수 있어요");
    emitEvent(mapId, "public", "map.deleted", { map_id: mapId });
    // #464 — 삭제한 지도는 30일 동안 휴지통에 있다(복구 가능). 마법 id map_purged는 31일 전에 삭제한 것으로 둔다
    const ageDays = mapId === "map_purged" ? 31 : 0;
    store.trashedMaps[mapId] = { map: store.maps[mapId], members: store.members[mapId] ?? [], deleted_at: new Date(Date.now() - ageDays * 86400000).toISOString() };
    delete store.maps[mapId];
    delete store.members[mapId];
    return new HttpResponse(null, { status: 204 });
  }),

  // #1446 지도 복사 — 방장만. 날짜·지역·색·대표 이미지·공개 핀만 옮긴다(핀은 내가 찍은 일반 핀으로). 반응·구성원·확정 리스트·추천 기록은 옮기지 않는다.
  http.post("*/maps/:mapId/copy", ({ params }) => {
    const mapId = params.mapId as string;
    const gate = ownerGate(mapId);
    if (gate) return gate;
    if (store.users[ME_USER_ID]?.is_guest) return apiError(403, "GUEST_NOT_ALLOWED", "지도를 만들려면 카카오로 로그인해 주세요");
    if (myMapCount() >= MAP_LIMIT) return mapLimitError();
    const source = store.maps[mapId];
    const taken = new Set(Object.values(store.maps).filter((m) => (store.members[m.id] ?? []).some((x) => x.user_id === ME_USER_ID)).map((m) => m.title));
    const newId = nextId("map");
    store.maps[newId] = {
      id: newId, title: copyTitle(source.title, taken), start_date: source.start_date, end_date: source.end_date,
      ...(source.region ? { region: source.region } : {}), ...(source.color ? { color: source.color } : {}),
      member_count: 1, pin_count: 0, confirmed_count: 0, created_by: ME_USER_ID,
    };
    store.members[newId] = [{ user_id: ME_USER_ID, role: "owner", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true, is_guest: false }];
    store.shortlist[newId] = [];
    const cover = store.mapCovers[mapId];
    if (cover) store.mapCovers[newId] = { ...cover, updated_at: Math.floor(Date.now() / 1000) };
    for (const pin of Object.values(store.pins).filter((p) => p.map_id === mapId && p.visibility === "public")) {
      const { checks: _c, reason: _r, member_fulfillment: _f, place_source: _s, my_reaction: _m, ...rest } = pin;
      const copy: Pin = {
        ...rest, id: nextId("pin"), map_id: newId, kind: "일반", created_by: ME_USER_ID,
        created_by_display_name: store.users[ME_USER_ID]?.display_name ?? "나", created_at: new Date().toISOString(),
        checks: [], reaction_summary: { like: 0, against: 0 },
      };
      copy.permissions = pinPermissions(copy);
      store.pins[copy.id] = copy;
      store.reactions[copy.id] = [];
    }
    return HttpResponse.json(toMapResponse(store.maps[newId]), { status: 201 });
  }),

  http.post("*/maps/:mapId/restore", ({ params }) => {
    const mapId = params.mapId as string;
    if (store.maps[mapId] && (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID)) return HttpResponse.json(toMapResponse(store.maps[mapId])); // 이미 복구됨 — 연타 안전
    const trashed = store.trashedMaps[mapId];
    if (!trashed || !trashed.members.some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    if (!trashed.members.some((m) => m.user_id === ME_USER_ID && m.role === "owner")) return apiError(403, "FORBIDDEN", "방장만 지도를 복구할 수 있어요");
    if (Date.now() - new Date(trashed.deleted_at).getTime() >= 30 * 86400000) return apiError(410, "MAP_PURGED", "삭제한 지 30일이 지나 복구할 수 없어요");
    if (myMapCount() >= MAP_LIMIT) return mapLimitError();
    store.maps[mapId] = trashed.map;
    store.members[mapId] = trashed.members;
    delete store.trashedMaps[mapId];
    emitEvent(mapId, "public", "map.restored", { map_id: mapId });
    return HttpResponse.json(toMapResponse(store.maps[mapId]));
  }),

  // #369 지도 나가기 — 구성원 누구나. 방장이면 다음 사람에게 위임, 넘길 사람이 없으면 409.
  http.delete("*/maps/:mapId/members/me", ({ params }) => {
    const mapId = params.mapId as string;
    const map = getMapOr404(mapId);
    const members = store.members[mapId] ?? [];
    if (!map || !members.some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    let newOwner: string | null = null;
    if (isOwner(mapId)) {
      const next = successorOf(mapId);
      if (!next) return apiError(409, "OWNER_CANNOT_LEAVE", "넘길 사람이 없어 나갈 수 없어요. 지도를 삭제해 주세요");
      next.role = "owner";
      newOwner = next.user_id!;
    }
    store.members[mapId] = members.filter((m) => m.user_id !== ME_USER_ID);
    map.member_count = store.members[mapId].length;
    // 그 지도에서 내가 남긴 반응만 지운다. 핀·확정 리스트·run은 남는다.
    for (const pin of Object.values(store.pins).filter((p) => p.map_id === mapId)) {
      if (pin.id && store.reactions[pin.id]) store.reactions[pin.id] = store.reactions[pin.id].filter((r) => r.user_id !== ME_USER_ID);
    }
    emitEvent(mapId, "public", "member.left", { map_id: mapId, user_id: ME_USER_ID, new_owner_user_id: newOwner });
    return new HttpResponse(null, { status: 204 });
  }),

  http.post("*/maps/:mapId/invite", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    // #467: 내가 만든 유효한 링크가 있으면 새로 만들지 않고 그것을 돌려준다(남이 만든 링크는 재사용하지 않는다)
    const [reusable] = Object.entries(store.invites).filter(([, i]) => i.mapId === mapId && i.created_by === ME_USER_ID && !inviteGone(i));
    if (reusable) {
      const [rtoken, r] = reusable;
      return HttpResponse.json({ token: rtoken, url: `https://pingo.example.com/invites/${rtoken}`, expires_at: r.expires_at }, { status: 200 });
    }
    const token = nextId("invite");
    const expires_at = new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString();
    store.invites[token] = { mapId, expires_at, created_at: new Date().toISOString(), created_by: ME_USER_ID, used_count: 0 };
    return HttpResponse.json({ token, url: `https://pingo.example.com/invites/${token}`, expires_at }, { status: 201 });
  }),

  // #467 초대 링크 목록 — 방장만. 끈 링크·만료 링크는 빠진다. 최신순
  http.get("*/maps/:mapId/invites", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId) || !(store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    if (!isOwner(mapId)) return apiError(403, "FORBIDDEN", "방장만 초대 링크를 관리할 수 있어요");
    const list = Object.entries(store.invites)
      .filter(([, i]) => i.mapId === mapId && !inviteGone(i))
      .map(([token, i]) => ({
        token,
        url: `https://pingo.example.com/invites/${token}`,
        expires_at: i.expires_at,
        created_at: i.created_at ?? i.expires_at,
        created_by_display_name: store.users[i.created_by ?? ME_USER_ID]?.display_name ?? "나",
        used_count: i.used_count ?? 0,
      }))
      .sort((a, b) => b.created_at.localeCompare(a.created_at));
    return HttpResponse.json(list);
  }),

  // #467 초대 링크 끄기 — 그 지도의 방장만. 이미 꺼도 204(멱등)
  http.delete("*/invites/:token", ({ params }) => {
    const invite = store.invites[params.token as string];
    if (!invite || !getMapOr404(invite.mapId)) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요");
    if (!isOwner(invite.mapId)) return apiError(403, "FORBIDDEN", "방장만 초대 링크를 끌 수 있어요");
    invite.revoked = true;
    return new HttpResponse(null, { status: 204 });
  }),

  // 초대 요약 — 로그인 없이 호출 가능(#23). 지도 내용은 주지 않는다
  http.get("*/invites/:token", ({ params }) => {
    const invite = store.invites[params.token as string];
    if (!invite) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요");
    const gone = inviteGone(invite);
    if (gone) return gone;
    const map = getMapOr404(invite.mapId);
    if (!map) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요");
    return HttpResponse.json({
      title: map.title,
      start_date: map.start_date,
      end_date: map.end_date,
      member_count: store.members[map.id]?.length ?? map.member_count ?? 0,
      pin_count: pinCount(map.id), // 핀의 이름·위치는 주지 않고 개수만
      inviter_display_name: store.members[map.id]?.[0]?.display_name,
      expires_at: invite.expires_at,
      // #1625 카드 그림 — 지역과 토큰으로 여는 대표 이미지(올린 게 없으면 키가 없다)
      ...(map.region ? { region: map.region } : {}),
      ...(store.mapCovers[map.id] ? { cover_url: `/invites/${params.token as string}/cover?v=${store.mapCovers[map.id].updated_at}` } : {}),
      // #1563 내가 이미 구성원이면 지도 id를 준다(아니면 필드 없음)
      ...((store.members[map.id] ?? []).some((m) => m.user_id === ME_USER_ID) ? { already_member_map_id: map.id } : {}),
    });
  }),

  http.get("*/invites/:token/cover", ({ params }) => {
    const invite = store.invites[params.token as string];
    if (!invite) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요");
    const gone = inviteGone(invite);
    if (gone) return gone;
    const cover = store.mapCovers[invite.mapId];
    if (!cover) return apiError(404, "NOT_FOUND", "대표 이미지가 없어요");
    return new HttpResponse(cover.data, {
      headers: { "Content-Type": cover.content_type, "Cache-Control": "private, max-age=31536000, immutable" },
    });
  }),

  http.post("*/invites/:token/accept", ({ params }) => {
    const invite = store.invites[params.token as string];
    if (!invite) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요");
    const gone = inviteGone(invite);
    if (gone) return gone;
    const map = getMapOr404(invite.mapId);
    if (!map) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요"); // 삭제된 지도의 토큰(#369)
    const members = store.members[invite.mapId] ?? (store.members[invite.mapId] = []);
    if (!members.some((m) => m.user_id === ME_USER_ID)) {
      if (myMapCount() >= MAP_LIMIT) return mapLimitError(); // 이미 구성원이면 새 참여가 아니라 막지 않는다
      members.push({ user_id: ME_USER_ID, role: "member", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true, is_guest: false });
      map.member_count = members.length;
      invite.used_count = (invite.used_count ?? 0) + 1;
    }
    return HttpResponse.json(toMapResponse(map));
  }),

  // #1556 마지막으로 본 때 — 목 서버는 메모리에만 둔다(나 한 사람)
  http.post("*/maps/:mapId/seen", async ({ params, request }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId) || !(store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    // #1672 본문의 seen_at(받아 둔 as_of)은 지금보다 뒤로 못 가고, 적어 둔 값보다 앞이면 그대로 둔다
    const raw = await request.text();
    const body = (raw ? JSON.parse(raw) : {}) as { seen_at?: string };
    const now = new Date().toISOString();
    if (body.seen_at !== undefined && Number.isNaN(Date.parse(body.seen_at))) return apiError(422, "VALIDATION_ERROR", "seen_at이 날짜와 시각이 아니에요");
    const at = body.seen_at && body.seen_at < now ? new Date(body.seen_at).toISOString() : now;
    lastSeen[mapId] = lastSeen[mapId] && lastSeen[mapId] > at ? lastSeen[mapId] : at;
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/maps/:mapId/news", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId) || !(store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const since = lastSeen[mapId] ?? null;
    const as_of = new Date().toISOString();   // #1672 이 응답을 만든 시각
    if (since === null) return HttpResponse.json({ since: null, as_of, new_pin_ids: [], new_reactions: [], truncated: false });
    const pins = Object.values(store.pins).filter((p) => p.map_id === mapId);
    const newPins = pins.filter((p) => p.created_by !== ME_USER_ID && p.created_at > since)
      .sort((a, b) => b.created_at.localeCompare(a.created_at)).map((p) => p.id);
    const nameOf = (userId: string) => (store.members[mapId] ?? []).find((m) => m.user_id === userId)?.display_name ?? "구성원";
    const newReactions = pins.flatMap((p) => (store.reactions[p.id] ?? [])
      .filter((r) => r.user_id !== ME_USER_ID && (r.updated_at ?? "") > since)
      .map((r) => ({ pin_id: p.id, user_id: r.user_id, display_name: nameOf(r.user_id), type: r.type, ...(r.reason_text ? { reason_text: r.reason_text } : {}),
        reason_chip_ids: r.reason_chip_ids ?? [], updated_at: r.updated_at as string })))
      .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    return HttpResponse.json({ since, as_of, new_pin_ids: newPins.slice(0, 100), new_reactions: newReactions.slice(0, 100),
      truncated: newPins.length > 100 || newReactions.length > 100 });
  }),

  http.get("*/maps/:mapId/members", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    // #1562 구성원마다 이 지도의 핀에 남긴 ♥·🚫 수(지운 핀은 store.pins에 없다)
    const pinIds = Object.values(store.pins).filter((p) => p.map_id === mapId).map((p) => p.id);
    const opinions = (userId: string) => pinIds.filter((id) => (store.reactions[id] ?? []).some((r) => r.user_id === userId)).length;
    return HttpResponse.json((store.members[mapId] ?? []).map((m) => ({ ...m, opinion_count: opinions(m.user_id) })));
  }),
];
