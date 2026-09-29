import { http, passthrough } from "msw";
import { authHandlers } from "./auth";
import { mapsHandlers } from "./maps";
import { pinsHandlers } from "./pins";
import { realtimeHandlers } from "./realtime";
import { recommendHandlers } from "./recommend";
import { shortlistHandlers } from "./shortlist";

/**
 * 외부 지도 SDK·타일 요청은 목 서버가 건드리지 않고 그대로 내보낸다(#139).
 *
 * API 핸들러는 도메인을 와일드카드로 두고 경로만 본다(예: maps/:mapId) — FE가 어떤 baseURL을
 * 쓰든 잡히게 하려는 것인데, 그 대가로 카카오맵 SDK 주소(dapi.kakao.com/v2/maps/sdk.js)까지
 * "지도 조회"로 착각해 404를 돌려줬다. msw는 목록 앞쪽 핸들러가 먼저 매칭되므로 이 규칙을 반드시 맨 앞에 둔다.
 * 새 외부 호스트를 쓰게 되면 여기에 추가한다.
 */
const externalPassthrough = http.all(
  /^https:\/\/([^/]+\.)?(kakao\.com|daumcdn\.net|kakaocdn\.net)\//,
  () => passthrough(),
);

/** docs/api-spec.yaml 29개 경로 전부를 커버하는 핸들러 모음(realtime SSE 2개, GET /maps 포함) */
export const handlers = [
  externalPassthrough,
  ...authHandlers,
  ...mapsHandlers,
  ...pinsHandlers,
  ...recommendHandlers,
  ...shortlistHandlers,
  ...realtimeHandlers,
];
