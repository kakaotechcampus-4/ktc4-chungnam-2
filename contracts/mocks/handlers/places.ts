import { http, HttpResponse } from "msw";
import type { components } from "../../src/types/api";
import { apiError } from "../util";
import { CATEGORY_RULES } from "../categories";

type PlaceSearchResult = components["schemas"]["PlaceSearchResult"];

/** 목 서버용 고정 장소 목록 — 실제 카카오 응답이 아니다. 이름 부분 일치로만 거른다. */
export const SEED_PLACES: PlaceSearchResult[] = [
  { place_id: "kakao:mock-1", place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639, category: "음식점", address: "부산 해운대구 우동", place_source: { provider: "kakao", url: "https://place.map.kakao.com/mock-1" } },
  { place_id: "kakao:mock-2", place_name: "해운대 바다 카페", lat: 35.1587, lng: 129.1604, category: "카페", address: "부산 해운대구 중동", place_source: { provider: "kakao", url: "https://place.map.kakao.com/mock-2" } },
  { place_id: "kakao:mock-3", place_name: "광안리 해변", lat: 35.1532, lng: 129.1186, category: "관광지", address: "부산 수영구 광안동", place_source: { provider: "kakao" } },
  { place_id: "kakao:mock-4", place_name: "광안리 게스트하우스", lat: 35.1547, lng: 129.1191, category: "숙소", address: "부산 수영구 광안동", place_source: { provider: "kakao" } },
  { place_id: "kakao:mock-5", place_name: "제주 흑돼지 거리", lat: 33.5131, lng: 126.5296, category: "음식점", address: "제주 제주시 일도이동", place_source: { provider: "kakao" } },
  { place_id: "kakao:mock-6", place_name: "성수 노포 곱창", lat: 37.5445, lng: 127.0557, category: "음식점", address: "서울 성동구 성수동2가", place_source: { provider: "kakao", url: "https://place.map.kakao.com/mock-6" } },
];

/**
 * 카카오에는 있지만 자체 장소 DB에는 없는 장소(#382). 검색 결과는 pinnable:false 이고, `source: search` 로는 핀이 안 된다
 * (422 PLACE_NOT_SUPPORTED). `source: live`(실시간 핀)로만 남길 수 있다. 실서버에서 검색 결과의 약 9할이 이런 장소다.
 */
export const NOT_IN_OWN_DB = new Set(["kakao:mock-6"]);

function distanceScore(a: PlaceSearchResult, lat: number, lng: number) {
  return (a.lat - lat) ** 2 + (a.lng - lng) ** 2;
}

const toRad = (d: number) => (d * Math.PI) / 180;
/** 두 좌표 사이 거리(m) */
function meters(aLat: number, aLng: number, bLat: number, bLng: number) {
  const dLat = toRad(bLat - aLat);
  const dLng = toRad(bLng - aLng);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(aLat)) * Math.cos(toRad(bLat)) * Math.sin(dLng / 2) ** 2;
  return 2 * 6371000 * Math.asin(Math.sqrt(h));
}
const isPinnable = (p: PlaceSearchResult) => !NOT_IN_OWN_DB.has(p.place_id) && (!p.category || CATEGORY_RULES[p.category].pinnable);
/** 반경 100m 안 자체 DB 장소를 가까운 순 최대 5곳(#473, #474) */
function ownDbNear(lat: number, lng: number, category?: string | null) {
  return SEED_PLACES.filter((p) => isPinnable(p) && (!category || p.category === category))
    .map((p) => ({ p, d: meters(lat, lng, p.lat, p.lng) }))
    .filter(({ d }) => d <= 100)
    .sort((a, b) => a.d - b.d)
    .slice(0, 5)
    .map(({ p }) => ({ ...p, pinnable: true }));
}

export const placesHandlers = [
  // #473 지도를 눌러 핀 — 누른 자리에서 가까운 자체 DB 장소. 누른 좌표는 저장하지 않는다.
  http.get("*/places/nearest", ({ request }) => {
    const url = new URL(request.url);
    const lat = Number(url.searchParams.get("lat"));
    const lng = Number(url.searchParams.get("lng"));
    if (!url.searchParams.has("lat") || !url.searchParams.has("lng") || Math.abs(lat) > 90 || Math.abs(lng) > 180) {
      return apiError(422, "VALIDATION_ERROR", "lat·lng가 필요해요");
    }
    return HttpResponse.json(ownDbNear(lat, lng, url.searchParams.get("category"))); // 0개는 빈 배열 그대로(가드레일 2)
  }),

  // #474 지도 링크 해석 — 핀을 만들지 않고 아무것도 저장하지 않는다. 목 서버는 구글 place URL과 place.map.kakao.com/{id}만 안다.
  http.post("*/places/from-link", async ({ request }) => {
    const { url } = (await request.json()) as { url: string };
    let u: URL;
    try { u = new URL(url); } catch { return apiError(422, "LINK_NOT_SUPPORTED", "구글맵·카카오맵 링크만 붙일 수 있어요"); }
    if (u.hostname === "maps.app.goo.gl") return apiError(422, "LINK_UNRESOLVED", "링크에서 장소를 찾지 못했어요. 검색으로 남겨 주세요"); // 마법 링크: 단축 링크 해석 실패
    if (u.hostname === "place.map.kakao.com") {
      const id = u.pathname.split("/").filter(Boolean)[0];
      if (!id) return apiError(422, "LINK_UNRESOLVED", "링크에서 장소를 찾지 못했어요. 검색으로 남겨 주세요");
      const own = SEED_PLACES.filter((p) => p.place_id === `kakao:${id}` && isPinnable(p)).map((p) => ({ ...p, pinnable: true }));
      return HttpResponse.json({ provider: "kakao", kakao_place_id: `kakao:${id}`, matches: own, needs_search_query: own.length === 0 });
    }
    if (u.hostname === "www.google.com" || u.hostname === "google.com") {
      const m = decodeURIComponent(u.pathname).match(/\/maps\/place\/([^/]+)\/@(-?\d+\.\d+),(-?\d+\.\d+)/);
      if (!m) return apiError(422, "LINK_UNRESOLVED", "링크에서 장소를 찾지 못했어요. 검색으로 남겨 주세요");
      const name = m[1].replace(/\+/g, " ");
      return HttpResponse.json({ provider: "google", name_hint: name, matches: ownDbNear(Number(m[2]), Number(m[3])), needs_search_query: false });
    }
    return apiError(422, "LINK_NOT_SUPPORTED", "구글맵·카카오맵 링크만 붙일 수 있어요"); // 네이버·인스타·블로그 등
  }),

  http.get("*/places/search", ({ request }) => {
    const url = new URL(request.url);
    const q = (url.searchParams.get("q") ?? "").trim();
    const latRaw = url.searchParams.get("lat");
    const lngRaw = url.searchParams.get("lng");
    const limit = Number(url.searchParams.get("limit") ?? 10);

    if (q.length < 1 || q.length > 50) return apiError(422, "VALIDATION_ERROR", "검색어는 1~50자로 입력해 주세요");
    if ((latRaw === null) !== (lngRaw === null)) return apiError(422, "VALIDATION_ERROR", "lat과 lng는 함께 보내 주세요");
    if (!Number.isInteger(limit) || limit < 1 || limit > 15) return apiError(422, "VALIDATION_ERROR", "limit은 1~15");
    // FE가 장애 화면을 확인하려고 쓰는 마법 검색어
    if (q === "__unavailable__") return apiError(503, "PLACES_UNAVAILABLE", "지금은 장소를 검색할 수 없어요");

    let found = SEED_PLACES.filter((p) => p.place_name.includes(q));
    if (latRaw !== null && lngRaw !== null) {
      const lat = Number(latRaw);
      const lng = Number(lngRaw);
      found = [...found].sort((a, b) => distanceScore(a, lat, lng) - distanceScore(b, lat, lng));
    }
    // pinnable: 자체 DB에 짝이 있어 핀이 될 수 있는가 — 목 서버는 카테고리의 pinnable(숙소·기타 false)과 NOT_IN_OWN_DB 를 본다
    return HttpResponse.json(found.slice(0, limit).map((p) => ({ ...p, pinnable: !NOT_IN_OWN_DB.has(p.place_id) && (!p.category || CATEGORY_RULES[p.category].pinnable) }))); // 0개는 빈 배열 그대로(가드레일 2)
  }),
];
