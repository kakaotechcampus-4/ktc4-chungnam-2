/**
 * 인메모리 목 데이터 저장소.
 * 실제 백엔드가 아니라 FE 개발/시연용 — 요청마다 이 객체를 읽고 쓴다.
 * 상태 초기화는 scenarios.ts의 resetScenario()로 한다.
 */
import type { components } from "../src/types/api";

type Schemas = components["schemas"];
export type Pin = Schemas["Pin"];
// 저장하는 지도 필드. permissions·next_owner는 요청자 기준 계산값이라 응답할 때 붙인다(handlers/maps.ts, #369).
/** `created_by`는 목 서버 내부 값이다(스펙의 Map에는 없다) — `created_by_me`를 계산하는 데만 쓰고 응답에서는 뺀다. */
export type MapEntity = Omit<Schemas["Map"], "permissions" | "next_owner" | "my_role" | "created_by_me"> & { created_by?: string };
export type MapCreateRequest = Schemas["MapCreateRequest"];
export type MapRegion = Schemas["MapRegion"];
export type Member = Schemas["Member"];
export type Reaction = Schemas["Reaction"];
export type EvidenceLine = Schemas["EvidenceLine"];
export type Region = Schemas["Region"];
export type RecommendRun = Schemas["RecommendRun"];
export type Candidate = Schemas["Candidate"];
export type ShortlistItem = Schemas["ShortlistItem"];
export type Route = Schemas["Route"];
export type Invite = Schemas["Invite"];
export type User = Schemas["User"];
export type AgentSettings = Schemas["AgentSettings"];
export type AgentSuggestion = Schemas["AgentSuggestion"];
export type AgentSummary = Schemas["AgentSummary"];
export type RunAdvice = Schemas["RunAdvice"];
/** 추천 탭 광고(docs/ads.md, #642). on_map은 응답 때 계산한다. */
export type Ad = Schemas["Ad"];

/** v2 계획 보조 에이전트 제안(docs/agent-v2.md). status와 열람자는 서버 내부 값이라 응답에 싣지 않는다. */
export interface AgentSuggestionEntity {
  map_id: string;
  suggestion: AgentSuggestion;
  status: "active" | "accepted" | "dismissed" | "expired" | "superseded";
  viewed_by: string[];
}

/**
 * AI 코스 짜기 run(#334, #580 결정 전 초안). 스펙의 CourseRun과 같은 모양이다 — `npm run gen:types`로 api.d.ts를 다시 만든 뒤
 * `Schemas["CourseRun"]`으로 바꾼다(지금 api.d.ts에는 아직 없다). requested_by, polls는 목 서버 내부 값이라 응답에서 뺀다.
 */
export interface CourseRunMock {
  id: string;
  map_id: string;
  status: "queued" | "running" | "done" | "failed";
  outcome: "solved" | "solved_with_checks" | "unresolved" | "timeout" | null;
  failure_code: "INTERRUPTED" | "ENGINE_ERROR" | null;
  goals: { id: string; kind: string; label: string; met: boolean | null }[];
  unmatched: string[];
  steps: { stage: string; role: "해석" | "지휘" | "계산" | "검증" | "결정"; by: "ai" | "code" | "human"; by_detail: string | null; text: string }[];
  days: {
    date: string;
    slots: { pin_id: string; order: number; needs_check: boolean }[];
    legs: { from_pin_id: string; to_pin_id: string; approx_minutes: number }[];
  }[];
  violations: { kind: "closed" | "travel" | "member"; text: string }[];
  checks: { pin_id: string; text: string }[];
  excluded: { pin_id: string; reason: "NO_COORDINATES" | "OVER_LIMIT"; text: string }[];
  snapshot_at: string;
  stale: boolean;
  created_at: string;
  finished_at: string | null;
}
export interface CourseRunEntity {
  run: CourseRunMock;
  requested_by: string;
  polls: number; // GET 횟수 — 첫 GET은 running, 그다음부터 done(진행 화면의 폴링을 흉내)
  snapshot_pin_ids: string[];
}

/** 목 서버에서 "나"로 취급하는 사용자. 기획안 6절 시나리오의 요청자다. */
export const ME_USER_ID = "u_me";

/** docs/events.md 봉투 — SSE 목 핸들러(realtime.ts)가 이 로그를 폴링해서 흘려보낸다. */
export interface EventLogEntry {
  seq: number;
  map_id: string;
  channel: "public" | "private";
  recipient_user_id?: string; // channel === "private"일 때만 의미 있음
  type: string;
  data: unknown;
}

export interface StoreState {
  seq: number;
  users: Record<string, User>;
  maps: Record<string, MapEntity>;
  members: Record<string, Member[]>; // mapId -> members
  pins: Record<string, Pin>; // pinId -> pin
  reactions: Record<string, Reaction[]>; // pinId -> reactions
  evidenceLines: Record<string, EvidenceLine[]>; // runId -> lines
  regions: Record<string, Region[]>; // runId -> regions
  runs: Record<string, RecommendRun>; // runId -> run
  runRequestedBy: Record<string, string>; // runId -> user_id (run 요청자 기록)
  candidates: Record<string, Candidate[]>; // runId -> candidates
  shortlist: Record<string, ShortlistItem[]>; // mapId -> items
  routes: Record<string, Route[]>; // mapId -> 마지막으로 계산된 동선 (#30, POST로만 갱신)
  invites: Record<string, { mapId: string; expires_at: string; created_at?: string; created_by?: string; revoked?: boolean; used_count?: number }>; // token -> invite (#467)
  eventLog: EventLogEntry[]; // realtime.ts SSE 핸들러가 폴링하는 대상
  agentSettings: Record<string, AgentSettings>; // mapId -> 모드. 없으면 켜짐(기본값)
  agentSuggestions: Record<string, AgentSuggestionEntity>; // suggestionId -> 제안
  agentSummaries: Record<string, AgentSummary[]>; // mapId -> 카테고리별 우리 조건 요약
  runAdvice: Record<string, RunAdvice | null>; // runId -> 추천 막힘 조언. null이면 204
  courseRuns: Record<string, CourseRunEntity>; // runId -> AI 코스 run(#334)
  ads: Ad[]; // 진행 중인 광고(#642, 목 서버는 기간과 active를 따지지 않는다)
  adStats: Record<string, { served: number; clicks: number }>; // ad_id -> 집계(확인용, 응답에 싣지 않는다)
  notifications: Schemas["Notification"][]; // 내 알림함(#470) — 목 서버는 단일 사용자라 나만 있다
  notificationPrefs: Record<string, boolean>; // 알림 종류 -> 켜짐. 없으면 켜짐
  feedback: { id: string; user_id: string; message: string; category: string; map_id?: string; created_at: string }[]; // #10
}

function emptyState(): StoreState {
  return {
    seq: 0,
    users: {},
    maps: {},
    members: {},
    pins: {},
    reactions: {},
    evidenceLines: {},
    regions: {},
    runs: {},
    runRequestedBy: {},
    candidates: {},
    shortlist: {},
    routes: {},
    invites: {},
    eventLog: [],
    agentSettings: {},
    agentSuggestions: {},
    agentSummaries: {},
    runAdvice: {},
    courseRuns: {},
    ads: [],
    adStats: {},
    notifications: [],
    notificationPrefs: {},
    feedback: [],
  };
}

export const store: StoreState = emptyState();

export function resetStore(next: StoreState) {
  Object.keys(store).forEach((k) => delete (store as any)[k]);
  Object.assign(store, next);
}

/** SSE event_log.seq와 같은 개념 — 단조증가 값. 재생성/재계산 순서 판단 + eventLog 번호로 쓴다. */
export function nextSeq(): number {
  store.seq += 1;
  return store.seq;
}

/** docs/events.md 이벤트 발행 — 실제 record_event(db, event)의 목 서버 대응. 반환값은 seq. */
export function emitEvent(
  mapId: string,
  channel: "public" | "private",
  type: string,
  data: unknown,
  recipientUserId?: string,
): number {
  const seq = nextSeq();
  store.eventLog.push({ seq, map_id: mapId, channel, recipient_user_id: recipientUserId, type, data });
  return seq;
}

// 시드가 "pin_1"~"pin_3"처럼 작은 번호를 직접 쓰므로, 만들어지는 id는 100부터 센다 — 테스트 순서에 따라
// 새 핀 id가 시드 id와 겹치는 일이 없게 한다. resetScenario가 시나리오를 만들기 전에 카운터를 되돌린다.
const ID_START = 100;
let idCounter = ID_START;
export function resetIdCounter(): void {
  idCounter = ID_START;
}
export function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}_${idCounter}`;
}
