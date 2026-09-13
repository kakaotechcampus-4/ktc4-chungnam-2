import { HttpResponse } from "msw";
import type { components } from "../src/types/api";
import { ME_USER_ID, store, type Pin, type EvidenceLine, type ShortlistItem } from "./store";

type ErrorBody = components["schemas"]["Error"];

/** docs/errors.md 코드 카탈로그와 1:1로 맞춘 에러 응답 생성기 */
export function apiError(status: number, code: string, message: string, detail?: Record<string, unknown>) {
  const body: ErrorBody = { code, message, ...(detail ? { detail } : {}) };
  return HttpResponse.json(body, { status });
}

/** docs/permissions.md — 롤 → 범위+액션 판정을 목 서버에서도 그대로 흉내낸다. */
export function pinPermissions(pin: Pin) {
  return {
    can_react: true, // member.actions: pin.react
    can_revert: true, // member.actions: pin.revert (구성원 누구나)
    can_add_to_shortlist: pin.kind !== "확정",
    can_remove_from_shortlist: pin.kind === "확정",
    can_delete: true, // 결정 이슈(#25) 확정 전까지 목 서버는 항상 true로 둔다
  };
}

export function evidencePermissions(line: EvidenceLine) {
  return {
    can_disable: line.author_id === ME_USER_ID, // "자기가 쓴 것만" (5-5)
  };
}

export function shortlistPermissions(_item: ShortlistItem) {
  return {
    can_remove_from_shortlist: true, // 구성원 누구나 (5-3)
  };
}

export function getMapOr404(mapId: string) {
  const map = store.maps[mapId];
  if (!map) return null;
  return map;
}
