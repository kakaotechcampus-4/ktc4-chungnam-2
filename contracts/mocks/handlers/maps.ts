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
    permissions: { can_delete: owner, can_leave: !owner || next !== null },
    ...(detail && next ? { next_owner: { user_id: next.user_id!, display_name: next.display_name ?? "" } } : {}),
  };
}

export const mapsHandlers = [
  // #24: 로그인 직후 진입점 — 내가 구성원인 지도만, 최근 생성순(store.maps는 생성 순서대로
  // 키가 쌓이므로 reverse()면 충분하다). 속한 지도가 없으면 빈 배열.
  http.get("*/maps", () => {
    const mine = Object.entries(store.maps)
      .filter(([mapId]) => (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID))
      .map(([, map]) => toMapResponse(map))
      .reverse();
    return HttpResponse.json(mine);
  }),

  http.post("*/maps", async ({ request }) => {
    const body = (await request.json()) as {
      title: string; start_date: string; end_date: string; region?: MapRegion;
    };
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

  // #369 지도 삭제 — 방장만. 실서버는 soft delete지만 목 서버는 그냥 지운다(이후 모든 조회가 404, 초대 토큰도 404).
  http.delete("*/maps/:mapId", ({ params }) => {
    const mapId = params.mapId as string;
    const mine = (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID);
    if (!getMapOr404(mapId) || !mine) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    if (!isOwner(mapId)) return apiError(403, "FORBIDDEN", "방장만 지도를 삭제할 수 있어요");
    emitEvent(mapId, "public", "map.deleted", { map_id: mapId });
    delete store.maps[mapId];
    delete store.members[mapId];
    return new HttpResponse(null, { status: 204 });
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
    const token = nextId("invite");
    const expires_at = new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString();
    store.invites[token] = { mapId, expires_at };
    return HttpResponse.json({ token, url: `https://pingo.example.com/invites/${token}`, expires_at }, { status: 201 });
  }),

  // 초대 요약 — 로그인 없이 호출 가능(#23). 지도 내용은 주지 않는다
  http.get("*/invites/:token", ({ params }) => {
    const invite = store.invites[params.token as string];
    if (!invite) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요");
    if (new Date(invite.expires_at).getTime() < Date.now()) return apiError(410, "INVITE_EXPIRED", "초대 링크가 만료됐어요");
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
    if (new Date(invite.expires_at).getTime() < Date.now()) return apiError(410, "INVITE_EXPIRED", "초대 링크가 만료됐어요");
    const map = getMapOr404(invite.mapId);
    if (!map) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요"); // 삭제된 지도의 토큰(#369)
    const members = store.members[invite.mapId] ?? (store.members[invite.mapId] = []);
    if (!members.some((m) => m.user_id === ME_USER_ID)) {
      if (myMapCount() >= MAP_LIMIT) return mapLimitError(); // 이미 구성원이면 새 참여가 아니라 막지 않는다
      members.push({ user_id: ME_USER_ID, role: "member", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true });
      map.member_count = members.length;
    }
    return HttpResponse.json(toMapResponse(map));
  }),

  http.get("*/maps/:mapId/members", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(store.members[mapId] ?? []);
  }),
];
