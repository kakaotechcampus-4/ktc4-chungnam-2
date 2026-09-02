import { http, HttpResponse } from "msw";
import { ME_USER_ID, store } from "../store";
import { apiError } from "../util";

export const authHandlers = [
  http.get("*/auth/kakao/callback", () => {
    return new HttpResponse(null, { status: 302, headers: { Location: "/" } });
  }),

  http.get("*/auth/me", () => {
    const user = store.users[ME_USER_ID];
    if (!user) return apiError(401, "UNAUTHORIZED", "로그인이 필요합니다");
    return HttpResponse.json(user);
  }),

  http.post("*/auth/logout", () => new HttpResponse(null, { status: 204 })),

  http.post("*/auth/withdraw", () => new HttpResponse(null, { status: 204 })),
];
