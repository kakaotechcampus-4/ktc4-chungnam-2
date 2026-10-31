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
    // #855 탈퇴 계정이 복구 기간 안이면 로그인하지 않고(세션 없음) 선택 화면으로 보낸다. 쿼리에는 아무 개인정보도 싣지 않는다
    if (store.pendingLogin) {
      return new HttpResponse(null, { status: 302, headers: { Location: "/?login_pending=withdrawn_account" } });
    }
    // #560 게스트가 카카오로 전환하면 기록을 합치고 guest_merged=true로 돌려보낸다(목 서버는 내 계정이 게스트가 아니게 된다)
    const me = store.users[ME_USER_ID];
    if (me?.is_guest) {
      me.is_guest = false;
      return new HttpResponse(null, { status: 302, headers: { Location: "/?guest_merged=true" } });
    }
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

  // #855 탈퇴 계정 재로그인 — 선택 안내와 선택. 세션 없이(콜백이 내린 pending_account 쿠키로) 부른다. 목 서버는 store.pendingLogin이 그 쿠키 역할이다.
  http.get("*/auth/pending", () => {
    const pending = store.pendingLogin;
    if (!pending) return apiError(404, "NO_PENDING_LOGIN", "선택 시간이 지났어요. 카카오로 다시 시작해 주세요");
    const restoreUntil = new Date(new Date(pending.withdrawn_at).getTime() + 7 * 24 * 60 * 60 * 1000);
    return HttpResponse.json({
      display_name: pending.display_name,
      withdrawn_at: pending.withdrawn_at,
      restore_until: restoreUntil.toISOString(),
      days_left: Math.max(0, Math.ceil((restoreUntil.getTime() - Date.now()) / (24 * 60 * 60 * 1000))),
    });
  }),

  http.post("*/auth/pending", async ({ request }) => {
    const body = (await request.json().catch(() => ({}))) as { choice?: string };
    // additionalProperties: false — choice 말고 다른 필드가 오면 거절한다
    if (Object.keys(body).some((k) => k !== "choice")) return apiError(422, "VALIDATION_ERROR", "알 수 없는 필드가 있어요");
    if (body.choice !== "restart" && body.choice !== "restore") return apiError(422, "VALIDATION_ERROR", "choice는 restart 또는 restore여야 해요");
    if (!store.pendingLogin) return apiError(404, "NO_PENDING_LOGIN", "선택 시간이 지났어요. 카카오로 다시 시작해 주세요");
    const user = store.users[ME_USER_ID];
    store.pendingLogin = null; // 쿠키가 지워진다 — 같은 선택의 재전송은 404
    if (body.choice === "restore") {
      // 되살리면 같은 계정(같은 id)이고 남아 있던 지도 참여가 돌아온다
      return HttpResponse.json(user, { status: 200 });
    }
    // restart: **새 사용자**(다른 id, 지도 참여 없음). 기존 계정은 즉시 정리돼 되살릴 수 없다
    const id = nextId("u_new");
    const fresh = { ...user, id, display_name: user.display_name, is_guest: false } as typeof user;
    store.users[id] = fresh;
    return HttpResponse.json(fresh, { status: 201 });
  }),

  http.get("*/auth/me", () => {
    // #855 선택 대기 중에는 아직 로그인된 상태가 아니다(세션 없음)
    if (store.pendingLogin) return apiError(401, "UNAUTHORIZED", "로그인이 필요합니다");
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
