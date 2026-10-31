import { http, HttpResponse } from "msw";
import { ME_USER_ID, emitEvent, nextId, store, type MapEntity, type MapRegion } from "../store";
import { apiError, getMapOr404 } from "../util";

/** 지도 응답의 핀 수는 저장값이 아니라 지금 있는 핀에서 센다(핀을 찍거나 지우면 바로 달라진다). */
const pinCount = (mapId: string) => Object.values(store.pins).filter((p) => p.map_id === mapId && p.visibility === "public").length;
const withPinCount = <T extends { id: string }>(map: T) => ({ ...map, pin_count: pinCount(map.id) });

/** 내 지도 상한(#369, #433에서 10→20). 만들거나 참여한 지도 합산 — 목 서버는 삭제·나간 지도를 이미 지우므로 지금 속한 지도만 센다. */
export const MAP_LIMIT = 20;
const myMapCount = () => Object.keys(store.maps).filter((id) => (store.members[id] ?? []).some((m) => m.user_id === ME_USER_ID)).length;
const mapLimitError = () =>
  apiError(409, "MAP_LIMIT", `지도는 ${MAP_LIMIT}개까지 만들거나 참여할 수 있어요. 지도를 나가거나 삭제한 뒤 다시 시도해 주세요`, { limit: MAP_LIMIT, count: myMapCount() });

/** 방장이 나가면 방장이 될 사람(#369). 목 서버의 구성원 배열은 들어온 순서라 나 다음 첫 사람이다(탈퇴자 개념은 없다). */
const successorOf = (mapId: string) => (store.members[mapId] ?? []).find((m) => m.user_id !== ME_USER_ID) ?? null;
const isOwner = (mapId: string) => (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID && m.role === "owner");

/** 지도 응답 — 핀 수와 요청자(나) 기준 permissions를 붙이고, 상세에서만 next_owner를 채운다(#369). */
function toMapResponse(map: MapEntity, { detail = false } = {}) {
  const owner = isOwner(map.id);
  const next = owner ? successorOf(map.id) : null;
  const { created_by: createdBy, ...rest } = map;
  return {
    ...withPinCount(rest),
    my_role: owner ? ("owner" as const) : ("member" as const),
    created_by_me: createdBy === ME_USER_ID, // #340·회의 14번: 만든 사람이 위임해도 값은 그대로다(my_role과 달라질 수 있다)
    permissions: { can_delete: owner, can_leave: !owner || next !== null, can_edit: owner },
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
    return HttpResponse.json({ items: mine, limit: MAP_LIMIT }); // #623: 목록과 상한을 함께
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
    store.members[mapId] = [{ user_id: ME_USER_ID, role: "owner", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true }];
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
    const body = (await request.json()) as { title?: string; start_date?: string; end_date?: string; region?: MapRegion };
    const title = body.title ?? map.title;
    const start = body.start_date ?? map.start_date;
    const end = body.end_date ?? map.end_date;
    if (Object.keys(body).length === 0 || title.trim().length < 1 || title.length > 100 || end < start) {
      return apiError(422, "VALIDATION_ERROR", "지도 수정 값이 올바르지 않아요");
    }
    Object.assign(map, { title, start_date: start, end_date: end, ...(body.region ? { region: body.region } : {}) });
    emitEvent(mapId, "public", "map.updated", {
      map_id: mapId, title, start_date: start, end_date: end, ...(map.region ? { region: map.region } : {}),
    });
    return HttpResponse.json(toMapResponse(map, { detail: true }));
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
      members.push({ user_id: ME_USER_ID, role: "member", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true });
      map.member_count = members.length;
      invite.used_count = (invite.used_count ?? 0) + 1;
    }
    return HttpResponse.json(toMapResponse(map));
  }),

  http.get("*/maps/:mapId/members", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(store.members[mapId] ?? []);
  }),
];
