import { http, HttpResponse } from "msw";
import { ME_USER_ID, nextId, store, type Pin, type ReviewEntity } from "../store";
import { apiError } from "../util";

/**
 * 크레딧과 장소 후기(#432, docs/credits-reviews.md). 값은 실서버의 credits/constants.py와 같다 — 화면은 응답으로만 받는다.
 * 목 서버는 단일 사용자라 잔액은 "나"(ME_USER_ID) 것만 센다.
 */
export const INITIAL_CREDITS = 30;
export const PRICES = { recommend_run: 1, course: 1 } as const;
export const REVIEW_REWARD = 10;
const REVIEW_BODY_MAX = 500;
const REVIEW_PAGE = 20;

export type CreditFeature = keyof typeof PRICES;

const isGuest = () => store.users[ME_USER_ID]?.is_guest === true;
const balance = () => store.credits[ME_USER_ID] ?? INITIAL_CREDITS; // 계정 행이 없으면 처음 지급량으로 본다(읽기는 쓰지 않는다)
const guestError = () => apiError(403, "GUEST_NOT_ALLOWED", "카카오로 로그인하면 크레딧을 드려요", { initial_credits: INITIAL_CREDITS });

/** check_can_spend — 게스트면 403, 모자라면 402. 통과하면 null. 모델(②)을 부르기 전 자리에서 부른다 */
export function creditGate(feature: CreditFeature) {
  if (isGuest()) return guestError();
  const price = PRICES[feature];
  if (balance() < price) return apiError(402, "CREDIT_INSUFFICIENT", "크레딧이 부족해요", { required: price, balance: balance() });
  return null;
}

/** charge — 실행을 새로 저장할 때. ref_id가 같으면 두 번 빼지 않는다 */
export function chargeCredit(feature: CreditFeature, runId: string) {
  const ref = `${feature}:${runId}`;
  if (store.creditRefs.includes(ref)) return;
  store.creditRefs.push(ref);
  store.credits[ME_USER_ID] = balance() - PRICES[feature];
}

/** refund — 결과 없이 끝난 실행. 멱등 */
export function refundCredit(feature: CreditFeature, runId: string) {
  const ref = `refund:${feature}:${runId}`;
  if (!store.creditRefs.includes(`${feature}:${runId}`) || store.creditRefs.includes(ref)) return false;
  store.creditRefs.push(ref);
  store.credits[ME_USER_ID] = balance() + PRICES[feature];
  return true;
}

/** 목 서버에는 places.id가 없어서 자체 DB 핀의 이름과 좌표로 같은 장소를 가린다(실서버는 pins.api의 place_id) */
const placeKey = (pin: Pin) => `${pin.place_name}@${pin.lat},${pin.lng}`;
const isLive = (pin: Pin) => pin.source === "live";

const mine = (r: ReviewEntity) => ({ id: r.id, rating: r.rating, body: r.body, created_at: r.created_at, updated_at: r.updated_at });
const visible = (key: string) =>
  Object.values(store.reviews)
    .filter((r) => r.place_key === key && !r.hidden)
    .sort((a, b) => b.created_at.localeCompare(a.created_at) || b.id.localeCompare(a.id));

/** 핀을 찾고 후기를 붙일 수 있는지 본다. 비구성원·없는 핀은 404, 실시간 핀은 422 */
function reviewablePin(pinId: string) {
  const pin = store.pins[pinId];
  if (!pin) return { error: apiError(404, "NOT_FOUND", "핀을 찾을 수 없습니다") };
  if (isLive(pin)) return { error: apiError(422, "PLACE_NOT_SUPPORTED", "장소 정보가 없는 핀이라 후기를 남길 수 없어요") };
  return { key: placeKey(pin) };
}

export const creditsHandlers = [
  http.get("*/credits/me", () => {
    if (isGuest()) return guestError();
    return HttpResponse.json({ balance: balance(), prices: PRICES, review_reward: REVIEW_REWARD });
  }),

  // 작성자 이름·id는 내리지 않는다(#432 결정 B) — is_mine만
  http.get("*/pins/:pinId/reviews", ({ params, request }) => {
    const found = reviewablePin(params.pinId as string);
    if (found.error) return found.error;
    const all = visible(found.key);
    const cursor = new URL(request.url).searchParams.get("cursor");
    let start = 0;
    if (cursor) {
      start = all.findIndex((r) => r.id === cursor) + 1;
      if (start === 0) return apiError(422, "VALIDATION_ERROR", "cursor가 올바르지 않습니다");
    }
    const page = all.slice(start, start + REVIEW_PAGE);
    const my = all.find((r) => r.user_id === ME_USER_ID);
    const avg = all.length ? Math.round((all.reduce((s, r) => s + r.rating, 0) / all.length) * 10) / 10 : null;
    return HttpResponse.json({
      summary: { average_rating: avg, count: all.length },
      limits: { body_max: REVIEW_BODY_MAX },
      ...(my ? { mine: mine(my) } : {}),
      items: page.map((r) => ({ ...mine(r), is_mine: r.user_id === ME_USER_ID })),
      ...(start + REVIEW_PAGE < all.length ? { next_cursor: page[page.length - 1].id } : {}),
    });
  }),

  // 그 장소에 처음 쓰면 +10. 고치거나 지웠다 다시 써도 다시 받지 않는다(ref_id = review:<user>:<place>)
  http.put("*/pins/:pinId/reviews/me", async ({ params, request }) => {
    if (isGuest()) return guestError();
    const found = reviewablePin(params.pinId as string);
    if (found.error) return found.error;
    const body = (await request.json().catch(() => ({}))) as { rating?: unknown; body?: unknown };
    const text = typeof body.body === "string" ? body.body.trim() : "";
    if (!Number.isInteger(body.rating) || (body.rating as number) < 1 || (body.rating as number) > 5) {
      return apiError(422, "VALIDATION_ERROR", "별점은 1~5 사이 정수예요");
    }
    if (!text || text.length > REVIEW_BODY_MAX) return apiError(422, "VALIDATION_ERROR", `후기는 1~${REVIEW_BODY_MAX}자로 적어 주세요`);
    const now = new Date().toISOString();
    let review = Object.values(store.reviews).find((r) => r.place_key === found.key && r.user_id === ME_USER_ID);
    if (review) {
      Object.assign(review, { rating: body.rating as number, body: text, updated_at: now });
    } else {
      review = { id: nextId("review"), place_key: found.key, user_id: ME_USER_ID, rating: body.rating as number, body: text, created_at: now, updated_at: now, hidden: false };
      store.reviews[review.id] = review;
    }
    const ref = `review:${ME_USER_ID}:${found.key}`;
    let credited = 0;
    if (!store.creditRefs.includes(ref)) {
      store.creditRefs.push(ref);
      store.credits[ME_USER_ID] = balance() + REVIEW_REWARD;
      credited = REVIEW_REWARD;
    }
    return HttpResponse.json({ review: mine(review), credited, balance: balance() });
  }),

  http.delete("*/pins/:pinId/reviews/me", ({ params }) => {
    const found = reviewablePin(params.pinId as string);
    if (found.error) return found.error.status === 422 ? apiError(404, "NOT_FOUND", "내 후기가 없습니다") : found.error;
    const review = Object.values(store.reviews).find((r) => r.place_key === found.key && r.user_id === ME_USER_ID);
    if (!review) return apiError(404, "NOT_FOUND", "내 후기가 없습니다");
    delete store.reviews[review.id];
    delete store.reviewReports[review.id];
    return new HttpResponse(null, { status: 204 });
  }),

  // 한 사람 한 번(이미 했어도 204). 내 후기는 422. 신고만으로 숨기지 않는다(#432 D8)
  http.post("*/reviews/:reviewId/reports", ({ params }) => {
    if (isGuest()) return guestError();
    const review = store.reviews[params.reviewId as string];
    if (!review || review.hidden) return apiError(404, "NOT_FOUND", "후기를 찾을 수 없습니다");
    if (review.user_id === ME_USER_ID) return apiError(422, "VALIDATION_ERROR", "내 후기는 신고할 수 없어요");
    const reporters = (store.reviewReports[review.id] ??= []);
    if (!reporters.includes(ME_USER_ID)) reporters.push(ME_USER_ID);
    return new HttpResponse(null, { status: 204 });
  }),
];
