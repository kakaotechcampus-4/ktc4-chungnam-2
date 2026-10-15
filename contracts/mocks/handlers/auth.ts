import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store } from "../store";

/** 초대 토큰 하나로 만들 수 있는 게스트 수(#472, docs/api-spec.yaml POST /auth/guest) */
export const GUEST_PER_INVITE_LIMIT = 10;
import { apiError } from "../util";

export const authHandlers = [
  // #128 — 로그인 시작은 BE가 카카오로 보낸다. 목 서버는 로그인된 것처럼 진입점으로 돌려보낸다.
  http.get("*/auth/kakao/login", () => {
    return new HttpResponse(null, { status: 302, headers: { Location: "/" } });
  }),

  http.get("*/auth/kakao/callback", () => {
    return new HttpResponse(null, { status: 302, headers: { Location: "/" } });
  }),

  // #472 게스트로 참여 — 이름만 입력, 초대 토큰으로 바로 지도에 들어간다. 목 서버는 단일 사용자라 세션은 바꾸지 않고
  // 게스트 계정·구성원 행만 만든다. 토큰 하나당 게스트 10명(GUEST_LIMIT).
  http.post("*/auth/guest", async ({ request }) => {
    const body = (await request.json()) as { display_name?: string; invite_token?: string };
    const name = (body.display_name ?? "").trim();
    if (!name || name.length > 50) return apiError(422, "VALIDATION_ERROR", "이름은 1~50자로 입력해 주세요");
    const invite = body.invite_token ? store.invites[body.invite_token] : undefined;
    const map = invite ? store.maps[invite.mapId] : undefined;
    if (!invite || !map) return apiError(404, "INVITE_NOT_FOUND", "유효하지 않은 초대 링크예요");
    if (invite.revoked) return apiError(410, "INVITE_REVOKED", "방장이 이 초대 링크를 껐어요");
    if (new Date(invite.expires_at).getTime() < Date.now()) return apiError(410, "INVITE_EXPIRED", "초대 링크가 만료됐어요");
    const guests = Object.values(store.users).filter((u) => (u as { guest_invite_token?: string }).guest_invite_token === body.invite_token);
    if (guests.length >= GUEST_PER_INVITE_LIMIT) return apiError(409, "GUEST_LIMIT", "이 링크로는 더 입장할 수 없어요");
    const id = nextId("u_guest");
    const user = { id, display_name: name, is_guest: true, guest_invite_token: body.invite_token } as (typeof store.users)[string];
    store.users[id] = user;
    store.members[map.id] = [...(store.members[map.id] ?? []), { user_id: id, display_name: name, role: "member" } as never];
    map.member_count = (map.member_count ?? 0) + 1;
    invite.used_count = (invite.used_count ?? 0) + 1;
    const { guest_invite_token: _omit, ...publicUser } = user as typeof user & { guest_invite_token?: string };
    return HttpResponse.json({ user: publicUser, map }, { status: 201 });
  }),

  http.get("*/auth/me", () => {
    const user = store.users[ME_USER_ID];
    if (!user) return apiError(401, "UNAUTHORIZED", "로그인이 필요합니다");
    return HttpResponse.json(user);
  }),

  http.patch("*/auth/me", async ({ request }) => {
    const user = store.users[ME_USER_ID];
    if (!user) return apiError(401, "UNAUTHORIZED", "로그인이 필요합니다");
    const body = (await request.json()) as { display_name?: string };
    const name = (body.display_name ?? "").trim();
    if (!name || name.length > 50) return apiError(422, "VALIDATION_ERROR", "이름은 1~50자로 입력해 주세요");
    user.display_name = name;
    return HttpResponse.json(user);
  }),

  http.post("*/auth/logout", () => new HttpResponse(null, { status: 204 })),

  http.post("*/auth/withdraw", () => new HttpResponse(null, { status: 204 })),
];
