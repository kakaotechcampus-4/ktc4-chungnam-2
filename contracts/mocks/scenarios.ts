/**
 * 시나리오 전환. docs/errors.md의 8종 화면과 대응한다.
 * FE에서: import { resetScenario } from "@pingo/contracts/mocks/scenarios"; resetScenario("no-results");
 */
import { ME_USER_ID, nextId, resetIdCounter, resetStore, type StoreState } from "./store";
import { buildBaseState, buildCandidates, buildEvidenceLines, buildRegions, SEED_MAP_ID } from "./seed";

export type ScenarioName = "empty" | "happy-path" | "no-results" | "retry-limit" | "region-conflict" | "guest" | "withdrawn-relogin" | "credits-empty";

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
  return state;
}

/** 폐지 예정(#432 D3, #954에서 지운다) — 10회째 run. 상한이 크레딧으로 바뀌어 이제 /retry도 그대로 된다. FE 시나리오 목록(#952)이 지울 때까지 이름만 남긴다 */
function buildRetryLimit(): StoreState {
  const state = buildBaseState();
  const runId = "run_retry_limit";
  state.runs[runId] = { id: runId, map_id: SEED_MAP_ID, category: "음식점", status: "done", attempt_no: 10 };
  state.runRequestedBy[runId] = ME_USER_ID;
  state.evidenceLines[runId] = buildEvidenceLines(runId);
  state.regions[runId] = buildRegions();
  state.candidates[runId] = buildCandidates("제주시 권역");
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

const BUILDERS: Record<ScenarioName, () => StoreState> = {
  empty: buildEmpty,
  "happy-path": buildHappyPath,
  "no-results": buildNoResults,
  "retry-limit": buildRetryLimit,
  "region-conflict": buildRegionConflict,
  guest: buildGuest,
  "withdrawn-relogin": buildWithdrawnRelogin,
  "credits-empty": buildCreditsEmpty,
};

export function resetScenario(name: ScenarioName) {
  resetIdCounter(); // 시나리오가 만드는 id가 테스트 순서와 무관하게 같다
  resetStore(BUILDERS[name]());
}

/** 기본값 — 목 서버 시작 시 최초 1회 자동 로드 */
export function loadDefaultScenario() {
  resetScenario("happy-path");
}
