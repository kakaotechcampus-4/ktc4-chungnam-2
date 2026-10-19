import { http, HttpResponse } from "msw";
import { ME_USER_ID, store, type Ad } from "../store";
import { apiError } from "../util";

/**
 * 추천 탭 광고(docs/ads.md, #642). 실서버 구현 전이라 목 서버가 계약을 먼저 연다.
 * 선택 규칙을 흉내만 낸다: 카테고리(없으면 전체), 반경, 요청자 최신 추천 결과와 겹침 제외, 최대 2개.
 * 목 서버 핀에는 자체 DB place_id가 없어서 on_map은 같은 이름의 핀이 있는지로 근사한다.
 */

const AD_SLOTS = 2;
const AD_RADIUS_M = 5000; // docs/ads.md 5절
const RECOMMEND_CATEGORIES = new Set(["음식점", "카페", "관광지"]);

function distanceM(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const dLat = (a.lat - b.lat) * 111_000;
  const dLng = (a.lng - b.lng) * 88_000;
  return Math.sqrt(dLat * dLat + dLng * dLng);
}

/** 요청자의 이 지도 최신 추천 결과에 있는 장소 이름(카테고리가 있으면 그 카테고리만). */
function latestRunPlaceNames(mapId: string, category: string | null): Set<string> {
  const mine = Object.values(store.runs).filter(
    (r) => r.map_id === mapId && store.runRequestedBy[r.id] === ME_USER_ID && (!category || r.category === category),
  );
  const names = new Set<string>();
  const latestByCategory = new Map<string, string>();
  for (const r of mine) latestByCategory.set(r.category, r.id); // 시드 순서가 생성순이라 마지막이 최신
  for (const runId of latestByCategory.values()) {
    for (const c of store.candidates[runId] ?? []) if (c.place_name) names.add(c.place_name);
  }
  return names;
}

function onMap(mapId: string, ad: Ad): boolean {
  return Object.values(store.pins).some((p) => p.map_id === mapId && p.place_name === ad.place.name);
}

function bump(adId: string, field: "served" | "clicks") {
  const stat = store.adStats[adId] ?? (store.adStats[adId] = { served: 0, clicks: 0 });
  stat[field] += 1;
}

export const adsHandlers = [
  http.get("*/maps/:mapId/ads", ({ params, request }) => {
    const mapId = params.mapId as string;
    if (!store.maps[mapId]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    const url = new URL(request.url);
    const category = url.searchParams.get("category");
    const lat = Number(url.searchParams.get("lat"));
    const lng = Number(url.searchParams.get("lng"));
    if (category && !RECOMMEND_CATEGORIES.has(category)) return apiError(422, "VALIDATION_ERROR", "추천 대상 카테고리가 아닙니다");
    if (!url.searchParams.has("lat") || !url.searchParams.has("lng") || !(Math.abs(lat) <= 90) || !(Math.abs(lng) <= 180)) {
      return apiError(422, "VALIDATION_ERROR", "lat, lng가 필요하고 범위 안이어야 합니다");
    }
    const excluded = latestRunPlaceNames(mapId, category);
    const picked = store.ads
      .filter((ad) => !category || ad.place.category === category)
      .filter((ad) => distanceM(ad.place, { lat, lng }) <= AD_RADIUS_M)
      .filter((ad) => !excluded.has(ad.place.name))
      .slice(0, AD_SLOTS) // 목 서버는 랜덤 대신 앞에서부터
      .map((ad) => ({ ...ad, on_map: onMap(mapId, ad) }));
    picked.forEach((ad) => bump(ad.ad_id, "served"));
    return HttpResponse.json({ ads: picked }, { headers: { "Cache-Control": "no-store" } });
  }),

  http.post("*/ads/:adId/clicks", async ({ params, request }) => {
    const adId = params.adId as string;
    const body = (await request.json()) as { map_id?: unknown };
    if (typeof body.map_id !== "string") return apiError(422, "VALIDATION_ERROR", "map_id가 필요합니다");
    if (!store.maps[body.map_id]) return apiError(404, "NOT_FOUND", "지도를 찾을 수 없습니다");
    if (!store.ads.some((ad) => ad.ad_id === adId)) return apiError(404, "NOT_FOUND", "광고를 찾을 수 없습니다");
    bump(adId, "clicks");
    return new HttpResponse(null, { status: 204 });
  }),
];
