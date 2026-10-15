/**
 * 기획안 6절 핵심 시나리오("로그인부터 확정까지")를 그대로 재현하는 시드 데이터.
 * scenarios.ts가 이 베이스를 상태별로 변형해서 쓴다.
 */
import { ME_USER_ID, nextId, type StoreState } from "./store";

const NOW = new Date().toISOString();
const minutesAgo = (m: number) => new Date(Date.now() - m * 60_000).toISOString();

export function buildBaseState(): StoreState {
  const mapId = "map_1";

  const users: StoreState["users"] = {
    [ME_USER_ID]: { id: ME_USER_ID, display_name: "황경" },
    u_2: { id: "u_2", display_name: "박서영" },
    u_3: { id: "u_3", display_name: "김도현" },
    u_4: { id: "u_4", display_name: "이유빈" },
  };

  const members: StoreState["members"] = {
    [mapId]: [
      { user_id: ME_USER_ID, role: "owner", display_name: "황경", online: true },
      { user_id: "u_2", role: "member", display_name: "박서영", online: true },
      { user_id: "u_3", role: "member", display_name: "김도현", online: false },
      { user_id: "u_4", role: "member", display_name: "이유빈", online: false },
    ],
  };

  const maps: StoreState["maps"] = {
    [mapId]: {
      id: mapId,
      title: "제주도 여행",
      start_date: "2026-10-10",
      end_date: "2026-10-12",
      member_count: 4,
      pin_count: 3,
      created_by: ME_USER_ID,
      confirmed_count: 0,
    },
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
      created_by: "u_2",
      created_by_display_name: "박서영",
      created_at: minutesAgo(180),
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 1, against: 1 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true, can_edit: false },
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
      created_by: ME_USER_ID,
      created_by_display_name: "황경",
      created_at: minutesAgo(50),
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 1, against: 1 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true, can_edit: true },
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
      created_by: "u_3",
      created_by_display_name: "김도현",
      created_at: minutesAgo(10),
      checks: [],
      source_run_id: null,
      reaction_summary: { like: 1, against: 0 },
      permissions: { can_react: true, can_revert: true, can_add_to_shortlist: true, can_remove_from_shortlist: false, can_delete: true, can_edit: false },
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
    routes: {},
    invites: {},
    eventLog: [],
    ...buildAgentState(mapId),
    notifications: [
      { id: "ntf_1", type: "pin_reaction", map_id: mapId, map_title: "제주도 여행", pin_id: "pin_1", message: "지우님이 내 핀에 ♥를 남겼어요", created_at: "2026-10-14T09:00:00Z", read: false },
      { id: "ntf_2", type: "member_joined", map_id: mapId, map_title: "제주도 여행", message: "민수님이 지도에 들어왔어요", created_at: "2026-10-13T09:00:00Z", read: true },
    ],
    notificationPrefs: {},
    feedback: [],
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
      author_display_name: "황경",
      text: "매워요",
      badge: "required" as const,
      fact_key: "spicy_focused",
      fact_label: "매운맛 전문",
      is_active: true,
      permissions: { can_disable: true },
    },
    {
      id: nextId("evi"),
      author_id: "u_3",
      author_display_name: "김도현",
      text: "비싸요",
      badge: "required" as const,
      fact_key: null, // 가격 라벨은 뺐다(#423). "비싸요"는 키 없는 근거 줄
      fact_label: null,
      is_active: true,
      permissions: { can_disable: false },
    },
    {
      id: nextId("evi"),
      author_id: "u_2",
      author_display_name: "박서영",
      text: "한식 말고 다른 거",
      badge: "required" as const,
      fact_key: "cuisine_korean",
      fact_label: "한식",
      wants: false, // 「한식 제외」 — 방향 표시(#228)
      is_active: true,
      permissions: { can_disable: false },
    },
    {
      id: nextId("evi"),
      author_id: "u_3",
      author_display_name: "김도현",
      text: "회 좋아해",
      badge: "preferred" as const,
      fact_key: "cuisine_raw_fish",
      fact_label: "횟집",
      wants: true, // 「횟집 선호」
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
      lat: 33.4996,
      lng: 126.5312,
      region_label: regionLabel,
      rank: 1,
      checks: [
        { fact_key: "spicy_focused", label: "매운맛 전문 아님", passed: true, confidence: "known" as const, needs_check: false },
        { fact_key: "parking_available", label: "주차 가능", passed: true, confidence: "known" as const, needs_check: false },
      ],
      visibility: "private" as const,
      published_pin_id: null,
      reason: "매운 음식을 피하는 조건을 지키고 주차도 돼요",
      member_fulfillment: { satisfied: 2, total: 2 },
      permissions: { can_publish: true },
    },
    {
      id: nextId("cand"),
      place_name: "제주보말칼국수",
      lat: 33.5072,
      lng: 126.5219,
      region_label: regionLabel,
      rank: 2,
      checks: [
        { fact_key: "spicy_focused", label: "매운맛 전문 아님", passed: true, confidence: "known" as const, needs_check: false },
        { fact_key: "parking_available", label: "주차 확인 필요", passed: true, confidence: "unknown" as const, needs_check: true },
      ],
      visibility: "private" as const,
      published_pin_id: null,
      reason: "매운맛 조건은 지키지만 주차는 확인이 필요해요",
      member_fulfillment: { satisfied: 1, total: 2 },
      permissions: { can_publish: true },
    },
    {
      id: nextId("cand"),
      place_name: "고기국수 명가",
      lat: 33.4891,
      lng: 126.4983,
      region_label: regionLabel,
      rank: 3,
      checks: [
        { fact_key: "spicy_focused", label: "매운맛 전문 아님", passed: true, confidence: "known" as const, needs_check: false },
        { fact_key: "parking_available", label: "주차 가능", passed: true, confidence: "known" as const, needs_check: false },
      ],
      visibility: "private" as const,
      published_pin_id: null,
      reason: "매운 음식을 피하는 조건을 지키고 주차도 돼요",
      member_fulfillment: { satisfied: 2, total: 2 },
      permissions: { can_publish: true },
    },
  ];
}

/**
 * v2 계획 보조 에이전트 시드(docs/agent-v2.md, #510). 지도 제안 하나(확정 리스트에 카페가 없음)와 음식점 우리 조건 요약 하나.
 * 문장은 실서버처럼 서버 렌더 결과를 그대로 둔다 — FE는 숫자나 슬롯을 다루지 않는다.
 */
export const SEED_SUGGESTION_ID = "sug_1";
export function buildAgentState(mapId: string): Pick<StoreState, "agentSettings" | "agentSuggestions" | "agentSummaries" | "runAdvice"> {
  const now = new Date("2026-10-15T09:00:00+09:00");
  return {
    agentSettings: {},
    agentSuggestions: {
      [SEED_SUGGESTION_ID]: {
        map_id: mapId,
        status: "active",
        viewed_by: [],
        suggestion: {
          id: SEED_SUGGESTION_ID,
          diagnosis: "category_gap",
          category: "카페",
          title: "확정 리스트에 카페가 아직 없어요",
          analysis: null,
          advice: [{ text: "확정 2곳 중 카페 0곳", is_guess: false }],
          actions: [
            { index: 0, type: "open_recommend", label: "카페 추천 받기", params: { category: "카페" } },
            { index: 1, type: "show_pins", label: "카페 핀 보기", params: { category: "카페" } },
          ],
          created_at: now.toISOString(),
          expires_at: new Date(now.getTime() + 24 * 3600 * 1000).toISOString(),
        },
      },
    },
    agentSummaries: {
      [mapId]: [
        {
          category: "음식점",
          must_keep: [{ fact_key: "spicy_focused", label: "매운 곳 제외", member_count: 1 }],
          common_prefs: [{ fact_key: "cuisine_raw_fish", label: "횟집 원함", member_count: 2 }],
          split_prefs: [{ fact_key: "franchise", label: "체인점", want_count: 1, avoid_count: 1 }],
          vague_fixable: { count: 1, requests: ["어떤 점이 별로였는지 적어 주시면 추천에 반영돼요"] },
          not_filtered: { count: 1, notices: ["알러지 같은 조건은 추천이 거르지 않아요. 가게에 직접 확인해 주세요."] },
          updated_at: now.toISOString(),
        },
      ],
    },
    runAdvice: {},
  };
}
