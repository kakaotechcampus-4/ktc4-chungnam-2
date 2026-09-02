/**
 * 기획안 6절 핵심 시나리오("로그인부터 확정까지")를 그대로 재현하는 시드 데이터.
 * scenarios.ts가 이 베이스를 상태별로 변형해서 쓴다.
 */
import { ME_USER_ID, nextId, type StoreState } from "./store";

const NOW = new Date().toISOString();

export function buildBaseState(): StoreState {
  const mapId = "map_1";

  const users: StoreState["users"] = {
    [ME_USER_ID]: { id: ME_USER_ID, display_name: "황경(나)" },
    u_2: { id: "u_2", display_name: "박서영" },
    u_3: { id: "u_3", display_name: "김도현" },
    u_4: { id: "u_4", display_name: "이유빈" },
  };

  const members: StoreState["members"] = {
    [mapId]: [
      { user_id: ME_USER_ID, display_name: "황경(나)", color: "#F97316", online: true },
      { user_id: "u_2", display_name: "박서영", color: "#3B82F6", online: true },
      { user_id: "u_3", display_name: "김도현", color: "#10B981", online: false },
      { user_id: "u_4", display_name: "이유빈", color: "#A855F7", online: false },
    ],
  };

  const maps: StoreState["maps"] = {
    [mapId]: { id: mapId, title: "제주도 여행", member_count: 4, confirmed_count: 0 },
  };

  // 음식점 핀 2개 — 각각 반응 2개씩(구성원 절반 = ceil(4/2) = 2) → 5-4 임계값 충족, 추천 버튼 활성화
  const pinFood1 = "pin_1";
  const pinFood2 = "pin_2";
  const pinCafe1 = "pin_3";

  const pins: StoreState["pins"] = {
    [pinFood1]: {
      id: pinFood1,
      map_id: mapId,
      category: "음식점",
      kind: "일반",
      visibility: "public",
      lat: 33.4996,
      lng: 126.5312,
      place_name: "흑돼지식당",
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 1, neutral: 0, against: 1 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true },
    },
    [pinFood2]: {
      id: pinFood2,
      map_id: mapId,
      category: "음식점",
      kind: "일반",
      visibility: "public",
      lat: 33.5015,
      lng: 126.5254,
      place_name: "우진해장국",
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 1, neutral: 0, against: 1 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true },
    },
    [pinCafe1]: {
      id: pinCafe1,
      map_id: mapId,
      category: "카페",
      kind: "일반",
      visibility: "public",
      lat: 33.489,
      lng: 126.4983,
      place_name: "카페 한라",
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 1, neutral: 0, against: 0 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true },
    },
  };

  const reactions: StoreState["reactions"] = {
    [pinFood1]: [
      { pin_id: pinFood1, user_id: ME_USER_ID, type: "against", reason_text: "매워요" },
      { pin_id: pinFood1, user_id: "u_2", type: "like", reason_text: "국물이 진해요" },
    ],
    [pinFood2]: [
      { pin_id: pinFood2, user_id: "u_3", type: "against", reason_text: "비싸요" },
      { pin_id: pinFood2, user_id: "u_4", type: "like", reason_text: "" },
    ],
    [pinCafe1]: [{ pin_id: pinCafe1, user_id: ME_USER_ID, type: "like", reason_text: "" }],
  };

  return {
    seq: 0,
    users,
    maps,
    members,
    pins,
    reactions,
    evidenceLines: {},
    regions: {},
    runs: {},
    runRequestedBy: {},
    candidates: {},
    shortlist: { [mapId]: [] },
    invites: {},
  };
}

export const SEED_MAP_ID = "map_1";
export const SEED_PIN_FOOD_1 = "pin_1";
export const SEED_PIN_FOOD_2 = "pin_2";
export const SEED_PIN_CAFE_1 = "pin_3";

/** 근거 리스트 시드 — 5-5: 같은 칩이라도 구성원별 한 줄씩. */
export function buildEvidenceLines(runId: string) {
  return [
    {
      id: nextId("evi"),
      author_id: ME_USER_ID,
      author_display_name: "황경(나)",
      text: "매워요",
      badge: "required" as const,
      fact_key: "spicy_focused",
      is_active: true,
      permissions: { can_disable: true },
    },
    {
      id: nextId("evi"),
      author_id: "u_3",
      author_display_name: "김도현",
      text: "비싸요",
      badge: "required" as const,
      fact_key: "price_bucket",
      is_active: true,
      permissions: { can_disable: false },
    },
    {
      id: nextId("evi"),
      author_id: "u_2",
      author_display_name: "박서영",
      text: "국물이 진해요",
      badge: "reference" as const,
      fact_key: null,
      is_active: true,
      permissions: { can_disable: false },
    },
  ];
}

export function buildRegions() {
  return [{ id: nextId("region"), label: "제주시 권역", signature: "sig-jeju-1", confirmed: true }];
}

export function buildCandidates(regionLabel: string) {
  return [
    {
      id: nextId("cand"),
      place_name: "올레국수",
      region_label: regionLabel,
      rank: 1,
      checks: [
        { fact_key: "spicy_focused", label: "매운맛 전문 아님", passed: true, confidence: "known" as const, needs_check: false },
        { fact_key: "price_bucket", label: "1인 12,000원", passed: true, confidence: "known" as const, needs_check: false },
      ],
      visibility: "private" as const,
      published_pin_id: null,
    },
    {
      id: nextId("cand"),
      place_name: "제주보말칼국수",
      region_label: regionLabel,
      rank: 2,
      checks: [
        { fact_key: "spicy_focused", label: "매운맛 전문 아님", passed: true, confidence: "known" as const, needs_check: false },
        { fact_key: "price_bucket", label: "가격대 확인 필요", passed: true, confidence: "unknown" as const, needs_check: true },
      ],
      visibility: "private" as const,
      published_pin_id: null,
    },
    {
      id: nextId("cand"),
      place_name: "고기국수 명가",
      region_label: regionLabel,
      rank: 3,
      checks: [
        { fact_key: "spicy_focused", label: "매운맛 전문 아님", passed: true, confidence: "known" as const, needs_check: false },
        { fact_key: "price_bucket", label: "1인 9,000원", passed: true, confidence: "known" as const, needs_check: false },
      ],
      visibility: "private" as const,
      published_pin_id: null,
    },
  ];
}
