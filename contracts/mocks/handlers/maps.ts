import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type MapRegion } from "../store";
import { apiError, getMapOr404 } from "../util";

/** 지도 응답의 핀 수는 저장값이 아니라 지금 있는 핀에서 센다(핀을 찍거나 지우면 바로 달라진다). */
const pinCount = (mapId: string) => Object.values(store.pins).filter((p) => p.map_id === mapId && p.visibility === "public").length;
const withPinCount = <T extends { id: string }>(map: T) => ({ ...map, pin_count: pinCount(map.id) });

export const mapsHandlers = [
  // #24: 로그인 직후 진입점 — 내가 구성원인 지도만, 최근 생성순(store.maps는 생성 순서대로
  // 키가 쌓이므로 reverse()면 충분하다). 속한 지도가 없으면 빈 배열.
  http.get("*/maps", () => {
    const mine = Object.entries(store.maps)
      .filter(([mapId]) => (store.members[mapId] ?? []).some((m) => m.user_id === ME_USER_ID))
      .map(([, map]) => withPinCount(map))
      .reverse();
    return HttpResponse.json(mine);
  }),

  http.post("*/maps", async ({ request }) => {
    const body = (await request.json()) as {
      title: string; start_date: string; end_date: string; region?: MapRegion;
    };
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
    };
    store.members[mapId] = [{ user_id: ME_USER_ID, role: "owner", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true }];
    store.shortlist[mapId] = [];
    // architecture.md 3절: 지도 생성 시 프리시딩 잡을 큐잉한다 — 목 서버에서는 즉시 "완료된 것처럼" 취급.
    // 지역(#22)이 있으면 그걸로, 없으면 첫 핀 좌표로 확정한다는 트리거 자체는 목 서버가 흉내낼
    // 필요가 없다(프리시딩은 백엔드 전용 부수효과라 FE가 관찰할 응답이 없다).
    return HttpResponse.json(withPinCount(store.maps[mapId]), { status: 201 });
  }),

  http.get("*/maps/:mapId", ({ params }) => {
    const map = getMapOr404(params.mapId as string);
    if (!map) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(withPinCount(map));
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
    if (!map) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const members = store.members[invite.mapId] ?? (store.members[invite.mapId] = []);
    if (!members.some((m) => m.user_id === ME_USER_ID)) {
      members.push({ user_id: ME_USER_ID, role: "member", display_name: store.users[ME_USER_ID]?.display_name ?? "나", online: true });
      map.member_count = members.length;
    }
    return HttpResponse.json(withPinCount(map));
  }),

  http.get("*/maps/:mapId/members", ({ params }) => {
    const mapId = params.mapId as string;
    if (!getMapOr404(mapId)) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    return HttpResponse.json(store.members[mapId] ?? []);
  }),
];
