/**
 * 인메모리 목 데이터 저장소.
 * 실제 백엔드가 아니라 FE 개발/시연용 — 요청마다 이 객체를 읽고 쓴다.
 * 상태 초기화는 scenarios.ts의 resetScenario()로 한다.
 */
import type { components } from "../src/types/api";

type Schemas = components["schemas"];
export type Pin = Schemas["Pin"];
export type MapEntity = Schemas["Map"];
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
  runRequestedBy: Record<string, string>; // runId -> user_id (5-5-1 비공개 판정에 사용)
  candidates: Record<string, Candidate[]>; // runId -> candidates
  shortlist: Record<string, ShortlistItem[]>; // mapId -> items
  routes: Record<string, Route[]>; // mapId -> 마지막으로 계산된 동선 (#30, POST로만 갱신)
  invites: Record<string, { mapId: string; expires_at: string }>; // token -> invite
  eventLog: EventLogEntry[]; // realtime.ts SSE 핸들러가 폴링하는 대상
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

let idCounter = 0;
export function nextId(prefix: string): string {
  idCounter += 1;
  return `${prefix}_${idCounter}`;
}
