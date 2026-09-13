import { authHandlers } from "./auth";
import { mapsHandlers } from "./maps";
import { pinsHandlers } from "./pins";
import { recommendHandlers } from "./recommend";
import { shortlistHandlers } from "./shortlist";

/** docs/api-spec.yaml 24개 경로 전부를 커버하는 핸들러 모음 */
export const handlers = [...authHandlers, ...mapsHandlers, ...pinsHandlers, ...recommendHandlers, ...shortlistHandlers];
