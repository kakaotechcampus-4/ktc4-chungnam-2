import { http, HttpResponse } from "msw";
import { ME_USER_ID, store } from "../store";
import { apiError } from "../util";

export const authHandlers = [
  // #128 — 로그인 시작은 BE가 카카오로 보낸다. 목 서버는 로그인된 것처럼 진입점으로 돌려보낸다.
  http.get("*/auth/kakao/login", () => {
    return new HttpResponse(null, { status: 302, headers: { Location: "/" } });
  }),

  http.get("*/auth/kakao/callback", () => {
    return new HttpResponse(null, { status: 302, headers: { Location: "/" } });
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
