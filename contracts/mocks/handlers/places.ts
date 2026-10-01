import { http, HttpResponse } from "msw";
import type { components } from "../../src/types/api";
import { apiError } from "../util";

type PlaceSearchResult = components["schemas"]["PlaceSearchResult"];

/** 목 서버용 고정 장소 목록 — 실제 카카오 응답이 아니다. 이름 부분 일치로만 거른다. */
export const SEED_PLACES: PlaceSearchResult[] = [
  { place_id: "kakao:mock-1", place_name: "해운대 밀면", lat: 35.1631, lng: 129.1639, category: "음식점", address: "부산 해운대구 우동", place_source: { provider: "kakao", url: "https://place.map.kakao.com/mock-1" } },
  { place_id: "kakao:mock-2", place_name: "해운대 바다 카페", lat: 35.1587, lng: 129.1604, category: "카페", address: "부산 해운대구 중동", place_source: { provider: "kakao", url: "https://place.map.kakao.com/mock-2" } },
  { place_id: "kakao:mock-3", place_name: "광안리 해변", lat: 35.1532, lng: 129.1186, category: "관광지", address: "부산 수영구 광안동", place_source: { provider: "kakao" } },
  { place_id: "kakao:mock-4", place_name: "광안리 게스트하우스", lat: 35.1547, lng: 129.1191, category: "숙소", address: "부산 수영구 광안동", place_source: { provider: "kakao" } },
  { place_id: "kakao:mock-5", place_name: "제주 흑돼지 거리", lat: 33.5131, lng: 126.5296, category: "음식점", address: "제주 제주시 일도이동", place_source: { provider: "kakao" } },
];

function distanceScore(a: PlaceSearchResult, lat: number, lng: number) {
  return (a.lat - lat) ** 2 + (a.lng - lng) ** 2;
}

export const placesHandlers = [
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
    return HttpResponse.json(found.slice(0, limit)); // 0개는 빈 배열 그대로(가드레일 2)
  }),
];
