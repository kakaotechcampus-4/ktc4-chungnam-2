/**
 * 시나리오 전환. docs/errors.md의 8종 화면과 대응한다.
 * FE에서: import { resetScenario } from "@pingo/contracts/mocks/scenarios"; resetScenario("no-results");
 */
import { ME_USER_ID, nextId, resetIdCounter, resetStore, type StoreState } from "./store";
import { buildBaseState, buildCandidates, buildEvidenceLines, buildRegions, SEED_MAP_ID, SEED_PIN_CAFE_1, SEED_SUGGESTION_ID } from "./seed";

export type ScenarioName = "empty" | "happy-path" | "no-results" | "region-conflict" | "guest" | "withdrawn-relogin" | "credits-empty" | "credits-full" | "agent-declared" | "agent-linked" | "agent-schedule";

/** 6절 "핀이 하나도 없음" 화면 — 지도만 있고 핀은 0개 */
function buildEmpty(): StoreState {
  const state = buildBaseState();
  state.pins = {};
  state.reactions = {};
  return state;
}

/** 기본 시나리오. 음식점 카테고리는 추천 버튼이 활성화된 상태(5-4)까지만 채워둔다 — 실제 run 생성부터는 FE가 API를 호출해서 진행한다. */
function buildHappyPath(): StoreState {
  return buildBaseState();
}

/** 6절 "결과 0개" — run이 실행됐지만 필터 통과 후보가 없다. GET /runs/{id}/result가 404 NO_RESULTS를 낸다. */
function buildNoResults(): StoreState {
  const state = buildBaseState();
  const runId = "run_no_results";
  state.runs[runId] = { id: runId, map_id: SEED_MAP_ID, category: "음식점", status: "done", attempt_no: 1 };
  state.runRequestedBy[runId] = ME_USER_ID;
  state.evidenceLines[runId] = buildEvidenceLines(runId);
  state.regions[runId] = buildRegions();
  state.candidates[runId] = []; // 필터 통과 0곳
  state.forceNoResults = true; // #1015 이 시나리오에서 새로 만든 run의 첫 실행도 0곳 — 크레딧을 돌려준다
  return state;
}

/** 5-6-1 "두 조건을 동시에 만족하는 곳이 없어요" — 지역 확인 대기 상태 */
function buildRegionConflict(): StoreState {
  const state = buildBaseState();
  const runId = "run_region_conflict";
  state.runs[runId] = { id: runId, map_id: SEED_MAP_ID, category: "관광지", status: "awaiting_region_confirm", attempt_no: 1 };
  state.runRequestedBy[runId] = ME_USER_ID;
  state.evidenceLines[runId] = [
    {
      id: nextId("evi"),
      author_id: ME_USER_ID,
      author_display_name: "황경",
      text: "해운대 기준 도보 5분",
      badge: "required",
      fact_key: "within_radius",
      is_active: true,
      permissions: { can_disable: true },
    },
    {
      id: nextId("evi"),
      author_id: "u_2",
      author_display_name: "박서영",
      text: "광안리 기준 도보 1분",
      badge: "required",
      fact_key: "within_radius",
      is_active: true,
      permissions: { can_disable: false },
    },
  ];
  state.regions[runId] = [
    { id: nextId("region"), label: "해운대 권역", signature: "sig-conflict-a", confirmed: false },
    { id: nextId("region"), label: "광안리 권역", signature: "sig-conflict-b", confirmed: false },
  ];
  return state;
}

/** #432 — 크레딧을 다 썼다. 추천 받기·코스 짜기는 402 CREDIT_INSUFFICIENT, 후기를 처음 쓰면 채워진다 */
/** #981 — 잔액이 상한(30)이다. 후기를 써도 크레딧을 받지 않는다(작성 시트가 미리 알린다) */
function buildCreditsFull(): StoreState {
  const state = buildBaseState();
  state.credits[ME_USER_ID] = 30;
  return state;
}

function buildCreditsEmpty(): StoreState {
  const state = buildBaseState();
  state.credits[ME_USER_ID] = 0;
  return state;
}

/** #472 — 내가 게스트다. 지도 만들기·추천·코스·크레딧·후기 쓰기는 403 GUEST_NOT_ALLOWED(#432), 나머지 구성원 행동은 그대로 */
function buildGuest(): StoreState {
  const state = buildBaseState();
  state.users[ME_USER_ID] = { ...state.users[ME_USER_ID], is_guest: true };
  return state;
}

/** #855 탈퇴한 계정으로 다시 로그인 — 복구 기간(7일) 안이라 카카오 콜백이 선택 화면으로 보낸다. 선택 전에는 로그인된 상태가 아니다. */
function buildWithdrawnRelogin(): StoreState {
  const state = buildBaseState();
  state.pendingLogin = { display_name: "탈퇴했던 나", withdrawn_at: new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString() };
  return state;
}

/**
 * #1345 — 「핑고 AI 조언」의 막힌 곳 한 살이 끝. 음식점 정체에서 추천 받기와 장소 검색을 해 봤는데도 새 핀이 없어
 * 지금 제안이 충돌 선언(attempt 2)이다. 버튼은 없고, 해 본 것 두 줄과 서버 문장만 있다. 지켜보던 음식점 줄은 tracking에서 빠진다.
 */
function buildAgentDeclared(): StoreState {
  const state = buildBaseState();
  const now = new Date("2026-10-15T09:00:00+09:00");
  const hoursAgo = (h: number) => new Date(now.getTime() - h * 3600 * 1000).toISOString();
  for (const e of Object.values(state.agentSuggestions)) e.status = "accepted";
  state.agentSuggestions["sug_declared"] = {
    map_id: SEED_MAP_ID,
    status: "active",
    viewed_by: [],
    suggestion: {
      id: "sug_declared",
      diagnosis: "stall",
      category: "음식점",
      title: "음식점은 해 본 방법으로 풀리지 않았어요",
      analysis: null,
      advice: [
        { segments: [{ kind: "text", text: "추천 받기와 장소 검색을 해 봤지만 반대 의견 뒤로 음식점에 새 핀이 없어요" }], is_guess: false },
        { segments: [{ kind: "text", text: "지금 조건으로 미리 찾으면 맞는 곳이 3곳 있어요" }], is_guess: false },
        { segments: [{ kind: "text", text: "어떤 조건을 지킬지는 여러분이 정해요" }], is_guess: false },
      ],
      actions: [], // 충돌 선언은 버튼이 없다
      facts: [],
      steps: [
        { stage: "감지", role: "계산", by: "code", by_detail: null, text: "음식점에 반대 의견 2개가 남은 뒤로 새 후보가 없어요" },
        { stage: "후속 확인", role: "계산", by: "code", by_detail: null, text: "장소 검색 뒤로 4시간 동안 음식점에 새 핀이 없었어요" },
        { stage: "미리 찾기", role: "계산", by: "code", by_detail: null, text: "지금 조건으로 미리 찾아봤어요 · 3곳 남아요" },
        { stage: "재확인", role: "검증", by: "code", by_detail: null, text: "저장 직전에 지도가 그대로인지 다시 봤어요" },
      ],
      attempt: 2,
      tried: [
        { action_type: "open_recommend", label: "음식점 추천 받기", accepted_at: hoursAgo(9) },
        { action_type: "search_place", label: "음식점 검색", accepted_at: hoursAgo(4) },
      ],
      created_at: now.toISOString(),
      expires_at: new Date(now.getTime() + 24 * 3600 * 1000).toISOString(),
    },
  };
  state.agentTracking[SEED_MAP_ID] = state.agentTracking[SEED_MAP_ID].filter((t) => t.suggestion_id !== "sug_watch"); // 지켜보던 음식점 줄이 지금 제안이 됐다
  return state;
}

/**
 * #1356 — 조언이 AI 코스 엔진(try_in_schedule)으로 지도의 카페 핀을 확정 일정에 끼워 보고 「이 핀 보기」(open_pin)로 넘긴다.
 * 시드의 카테고리 공백 제안(sug_1)을 모델 진단 결과로 바꾼다. 확정은 사람이 한다.
 */
function buildAgentLinked(): StoreState {
  const state = buildBaseState();
  const s = state.agentSuggestions[SEED_SUGGESTION_ID].suggestion;
  s.advice = [
    { segments: [{ kind: "text", text: "확정 2곳 중 카페 0곳" }], is_guess: false },
    {
      segments: [
        { kind: "pin", pin_id: SEED_PIN_CAFE_1, text: "카페 한라" },
        { kind: "text", text: "은 ♥ 2이고, 2일차 동선에 넣으면 이동이 6분 늘어요" },
      ],
      is_guess: false,
    },
  ];
  s.actions = [{ index: 0, type: "open_pin", label: "이 핀 보기", params: { pin_ids: [SEED_PIN_CAFE_1] } }];
  s.steps = [
    { stage: "감지", role: "계산", by: "code", by_detail: null, text: "확정한 2곳 중 카페가 없어요" },
    { stage: "미리 찾기", role: "계산", by: "code", by_detail: null, text: "지금 조건으로 미리 찾아봤어요 · 12곳 남아요" },
    { stage: "조사", role: "지휘", by: "ai", by_detail: null, text: "의견 사유 2개를 읽었어요" },
    { stage: "조사", role: "지휘", by: "ai", by_detail: null, text: "AI 코스 엔진으로 핀 2개를 일정에 끼워 봤어요" },
    { stage: "검증", role: "검증", by: "code", by_detail: null, text: "숫자와 인용 3개를 지도와 대조했어요" },
    { stage: "재확인", role: "검증", by: "code", by_detail: null, text: "저장 직전에 지도가 그대로인지 다시 봤어요" },
  ];
  return state;
}

/** #1356 — 사람이 넣은 일정에 쉬는 날 방문이 있어 조언이 「AI 코스로 고쳐 보기」(open_course)로 넘긴다. 코드 유형이다. */
function buildAgentSchedule(): StoreState {
  const state = buildBaseState();
  const s = state.agentSuggestions[SEED_SUGGESTION_ID].suggestion;
  s.diagnosis = "schedule";
  s.category = null;
  s.title = "일정에 다시 볼 곳이 있어요";
  s.advice = [
    {
      segments: [
        { kind: "text", text: "2일차에 쉬는 날인 곳이 있어요 · " },
        { kind: "pin", pin_id: SEED_PIN_CAFE_1, text: "카페 한라" },
      ],
      is_guess: false,
    },
  ];
  s.actions = [{ index: 0, type: "open_course", label: "AI 코스로 고쳐 보기", params: {} }];
  s.steps = [
    { stage: "감지", role: "계산", by: "code", by_detail: null, text: "AI 코스 점검으로 일정을 살펴봤어요 · 고칠 곳 1곳" },
    { stage: "재확인", role: "검증", by: "code", by_detail: null, text: "저장 직전에 지도가 그대로인지 다시 봤어요" },
  ];
  return state;
}

const BUILDERS: Record<ScenarioName, () => StoreState> = {
  empty: buildEmpty,
  "happy-path": buildHappyPath,
  "no-results": buildNoResults,
  "region-conflict": buildRegionConflict,
  guest: buildGuest,
  "withdrawn-relogin": buildWithdrawnRelogin,
  "credits-empty": buildCreditsEmpty,
  "credits-full": buildCreditsFull,
  "agent-declared": buildAgentDeclared,
  "agent-linked": buildAgentLinked,
  "agent-schedule": buildAgentSchedule,
};

export function resetScenario(name: ScenarioName) {
  resetIdCounter(); // 시나리오가 만드는 id가 테스트 순서와 무관하게 같다
  resetStore(BUILDERS[name]());
}

/** 기본값 — 목 서버 시작 시 최초 1회 자동 로드 */
export function loadDefaultScenario() {
  resetScenario("happy-path");
}
