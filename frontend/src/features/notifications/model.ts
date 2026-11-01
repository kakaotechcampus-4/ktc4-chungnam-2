import type { components } from '@pingo/contracts/src/types/api'

export type NotificationDto = components['schemas']['Notification']
export type NotificationListDto = components['schemas']['NotificationList']
export type NotificationType = components['schemas']['NotificationType']
export type NotificationPref = components['schemas']['NotificationPref']
export type NotificationPrefsDto = components['schemas']['NotificationPrefs']

/** 알림 설정 줄 이름. 종류 목록은 서버가 정한다(GET 응답 순서 그대로) — 여기 없는 종류는 서버 값을 그대로 적는다. */
const TYPE_LABEL: Record<NotificationType, string> = {
  pin_reaction: '내 핀에 의견이 달렸을 때',
  member_joined: '내 지도에 새 구성원이 들어왔을 때',
  owner_changed: '내가 방장이 됐을 때',
  map_deleted: '내가 있는 지도가 삭제됐을 때',
}
export const prefLabel = (type: string) => TYPE_LABEL[type as NotificationType] ?? type

/** 종 배지 — 99를 넘으면 99+(api-spec NotificationList.unread_count). 0이면 배지가 없다. */
export function badgeText(unread: number): string | null {
  if (unread <= 0) return null
  return unread > 99 ? '99+' : String(unread)
}

/**
 * 알림을 누르면 갈 곳(api-spec Notification). 핀 반응은 그 핀, 삭제된 지도는 내 지도 목록, 나머지는 그 지도.
 * 핀이 지워졌거나 지도를 나갔으면 그 화면이 404를 받아 스스로 처리한다.
 */
export function notificationTarget(n: Pick<NotificationDto, 'type' | 'map_id' | 'pin_id'>): string {
  if (n.type === 'map_deleted') return '/'
  if (n.type === 'pin_reaction' && n.pin_id) return `/maps/${n.map_id}?pin=${encodeURIComponent(n.pin_id)}`
  return `/maps/${n.map_id}`
}
