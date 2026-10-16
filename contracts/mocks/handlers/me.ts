import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store } from "../store";
import { apiError } from "../util";

/** NotificationType 선언 순서 — GET /me/notification-prefs는 이 순서로 전부 돌려준다(docs/api-spec.yaml) */
export const NOTIFICATION_TYPES = ["pin_reaction", "member_joined", "owner_changed", "map_deleted", "my_ai_pin_published"] as const;

const prefsBody = () => ({ prefs: NOTIFICATION_TYPES.map((type) => ({ type, enabled: store.notificationPrefs[type] ?? true })) });

/** #10 — 사용자당 시간당 10건. 목 서버는 시각 대신 개수로만 본다 */
const FEEDBACK_LIMIT = 10;

export const meHandlers = [
  // #470 알림함 — 최근순, before 커서, unread_only. unread_count는 페이지와 무관한 전체 수
  http.get("*/me/notifications", ({ request }) => {
    const url = new URL(request.url);
    const limit = Number(url.searchParams.get("limit") ?? 20);
    if (!Number.isInteger(limit) || limit < 1 || limit > 50) return apiError(422, "VALIDATION_ERROR", "limit은 1~50");
    const unreadOnly = url.searchParams.get("unread_only") === "true";
    const before = url.searchParams.get("before");
    const all = [...store.notifications].sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));
    let rows = unreadOnly ? all.filter((n) => !n.read) : all;
    if (before) {
      const at = rows.findIndex((n) => n.id === before);
      rows = at < 0 ? [] : rows.slice(at + 1);
    }
    const items = rows.slice(0, limit);
    return HttpResponse.json({
      items,
      unread_count: store.notifications.filter((n) => !n.read).length,
      ...(rows.length > limit ? { next_before: items[items.length - 1].id } : {}),
    });
  }),

  // 멱등 — 모르는 id는 조용히 무시, ids를 생략하면 전부
  http.post("*/me/notifications/read", async ({ request }) => {
    const text = await request.text();
    const body = (text ? JSON.parse(text) : {}) as { ids?: string[] };
    if (body.ids && body.ids.length > 100) return apiError(422, "VALIDATION_ERROR", "ids는 100개까지");
    for (const n of store.notifications) if (!body.ids || body.ids.includes(n.id)) n.read = true;
    return new HttpResponse(null, { status: 204 });
  }),

  http.get("*/me/notification-prefs", () => HttpResponse.json(prefsBody())),

  http.put("*/me/notification-prefs", async ({ request }) => {
    const body = (await request.json()) as { prefs?: { type: string; enabled: boolean }[] };
    if (!body.prefs?.length || body.prefs.some((p) => !(NOTIFICATION_TYPES as readonly string[]).includes(p.type) || typeof p.enabled !== "boolean")) {
      return apiError(422, "VALIDATION_ERROR", "알림 종류와 켜짐 여부가 필요해요");
    }
    for (const p of body.prefs) store.notificationPrefs[p.type] = p.enabled;
    return HttpResponse.json(prefsBody());
  }),

  // #10 서비스 피드백 — 저장만. 앞뒤 공백을 지운 뒤 비면 422, 시간당 10건 초과는 429
  http.post("*/feedback", async ({ request }) => {
    const body = (await request.json()) as { message?: string; category?: string; map_id?: string };
    const message = (body.message ?? "").trim();
    if (!message || message.length > 1000) return apiError(422, "VALIDATION_ERROR", "내용은 1~1000자로 적어 주세요");
    if (body.category !== undefined && !["bug", "idea", "other"].includes(body.category)) return apiError(422, "VALIDATION_ERROR", "분류는 bug·idea·other");
    if (store.feedback.length >= FEEDBACK_LIMIT) return apiError(429, "RATE_LIMITED", "잠시 뒤 다시 보내 주세요");
    const row = { id: nextId("fb"), user_id: ME_USER_ID, message, category: body.category ?? "other", ...(body.map_id ? { map_id: body.map_id } : {}), created_at: new Date().toISOString() };
    store.feedback.push(row);
    return HttpResponse.json({ id: row.id, created_at: row.created_at }, { status: 201 });
  }),
];
