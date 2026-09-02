import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store } from "../store";
import { apiError, getMapOr404 } from "../util";

export const mapsHandlers = [
  http.post("*/maps", async ({ request }) => {
    const body = (await request.json()) as { title: string; region_hint?: string };
    const mapId = nextId("map");
    store.maps[mapId] = { id: mapId, title: body.title, member_count: 1, confirmed_count: 0 };
    store.members[mapId] = [{ user_id: ME_USER_ID, display_name: store.users[ME_USER_ID]?.display_name ?? "나", color: "#F97316", online: true }];
    store.shortlist[mapId] = [];
    // architecture.md 3절: 지도 생성 시 프리시딩 잡을 큐잉한다 — 목 서버에서는 즉시 "완료된 것처럼" 취급
    return HttpResponse.json(store.maps[mapId], { status: 201 });
  }),

  http.get("*/maps/:mapId", ({ params }) => {
    const map = getMapOr404(params.mapId as string);
    if (!map) return apiError(404, "MAP_NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(map);
  }),

  http.post("*/maps/:mapId/invite", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId)) return apiError(404, "MAP_NOT_FOUND", "지도를 찾을 수 없습니다");
    const token = nextId("invite");
    const expires_at = new Date(Date.now() + 7 * 24 * 3600 * 1000).toISOString();
    store.invites[token] = { mapId, expires_at };
    return HttpResponse.json({ token, url: `https://pingo.example.com/invites/${token}`, expires_at }, { status: 201 });
  }),

  http.post("*/invites/:token/accept", ({ params }) => {
    const invite = store.invites[params.token as string];
    if (!invite) return apiError(401, "UNAUTHORIZED", "초대 링크가 유효하지 않습니다");
    const map = getMapOr404(invite.mapId);
    if (!map) return apiError(404, "MAP_NOT_FOUND", "지도를 찾을 수 없습니다");
    const members = store.members[invite.mapId] ?? (store.members[invite.mapId] = []);
    if (!members.some((m) => m.user_id === ME_USER_ID)) {
      members.push({ user_id: ME_USER_ID, display_name: store.users[ME_USER_ID]?.display_name ?? "나", color: "#EAB308", online: true });
      map.member_count = members.length;
    }
    return HttpResponse.json(map);
  }),

  http.get("*/maps/:mapId/members", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId)) return apiError(404, "MAP_NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(store.members[mapId] ?? []);
  }),
];
