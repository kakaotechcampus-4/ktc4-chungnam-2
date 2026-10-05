/**
 * docs/events.md — SSE 2채널. msw는 표준 Response(ReadableStream)를 그대로 반환할 수 있어서
 * 실제 EventSource로 열어도 동작한다(브라우저가 자동 재연결·Last-Event-ID를 처리).
 *
 * 실제 백엔드(realtime/core.py::advance)처럼 event_log를 500ms 주기로 폴링하는 방식을 그대로
 * 흉내낸다 — 폴링 기반이라는 성질 자체(순서 보장, at-least-once)를 프론트가 목 서버로도
 * 체감할 수 있게 한다.
 *
 * 현재 실제로 발행되는 이벤트: pin.created/pin.published/pin.deleted/reaction.changed
 * (pins.ts·recommend.ts에서 emitEvent 호출). 나머지(shortlist.changed, route.recalculated,
 * member 계열, run 계열)는 아직 안 붙였다 — 해당 화면(#17 이후, AI 추천 탭 등) 착수 시 같은
 * 패턴으로 emitEvent를 그 핸들러에 추가하면 된다.
 */
import { http } from "msw";
import { ME_USER_ID, store, type EventLogEntry } from "../store";

const POLL_MS = 500;

function sseResponse(mapId: string, lastEventId: number, matches: (entry: EventLogEntry) => boolean): Response {
  let cursor = lastEventId;
  const encoder = new TextEncoder();
  let timer: ReturnType<typeof setInterval>;

  const stream = new ReadableStream({
    start(controller) {
      timer = setInterval(() => {
        const pending = store.eventLog.filter((e) => e.map_id === mapId && e.seq > cursor && matches(e));
        for (const entry of pending) {
          cursor = entry.seq;
          const chunk = `id: ${entry.seq}\nevent: ${entry.type}\ndata: ${JSON.stringify(entry.data)}\n\n`;
          controller.enqueue(encoder.encode(chunk));
        }
      }, POLL_MS);
    },
    cancel() {
      clearInterval(timer);
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

export const realtimeHandlers = [
  http.get("*/maps/:mapId/events", ({ params, request }) => {
    const mapId = params.mapId as string;
    const lastEventId = Number(request.headers.get("Last-Event-ID") ?? 0);
    return sseResponse(mapId, lastEventId, (e) => e.channel === "public");
  }),

  http.get("*/maps/:mapId/events/me", ({ params, request }) => {
    const mapId = params.mapId as string;
    const lastEventId = Number(request.headers.get("Last-Event-ID") ?? 0);
    return sseResponse(mapId, lastEventId, (e) => e.channel === "private" && e.recipient_user_id === ME_USER_ID);
  }),
];
