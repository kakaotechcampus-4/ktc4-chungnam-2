/**
 * 시나리오 전환. docs/errors.md의 8종 화면과 대응한다.
 * FE에서: import { resetScenario } from "@pingo/contracts/mocks/scenarios"; resetScenario("no-results");
 */
import { ME_USER_ID, nextId, resetStore, type StoreState } from "./store";
import { buildBaseState, buildCandidates, buildEvidenceLines, buildRegions, SEED_MAP_ID } from "./seed";

export type ScenarioName = "empty" | "happy-path" | "no-results" | "retry-limit" | "region-conflict";

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

/** 6절 "재시도 3회 초과" — 이미 3회 시도한 run. 다음 /retry 호출은 429. */
function buildRetryLimit(): StoreState {
  const state = buildBaseState();
  const runId = "run_retry_limit";
  state.runs[runId] = { id: runId, map_id: SEED_MAP_ID, category: "음식점", status: "done", attempt_no: 3 };
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
  state.runs[runId] = { id: runId, map_id: SEED_MAP_ID, category: "숙소", status: "awaiting_region_confirm", attempt_no: 1 };
  state.runRequestedBy[runId] = ME_USER_ID;
  state.evidenceLines[runId] = [
    {
      id: nextId("evi"),
      author_id: ME_USER_ID,
      author_display_name: "황경(나)",
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

const BUILDERS: Record<ScenarioName, () => StoreState> = {
  empty: buildEmpty,
  "happy-path": buildHappyPath,
  "no-results": buildNoResults,
  "retry-limit": buildRetryLimit,
  "region-conflict": buildRegionConflict,
};

export function resetScenario(name: ScenarioName) {
  resetStore(BUILDERS[name]());
}

/** 기본값 — 목 서버 시작 시 최초 1회 자동 로드 */
export function loadDefaultScenario() {
  resetScenario("happy-path");
}
