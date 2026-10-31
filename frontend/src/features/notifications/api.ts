import { api } from '@/api'

import type { NotificationListDto, NotificationPref, NotificationPrefsDto } from './model'

/** 알림함(#470) — 최근순. `before`는 앞 응답의 next_before 그대로. */
export const fetchNotifications = (before?: string) =>
  api<NotificationListDto>(`/me/notifications${before ? `?${new URLSearchParams({ before })}` : ''}`)

/** 읽음 처리. ids를 빼면 전부. 멱등이다. */
export const markNotificationsRead = (ids?: string[]) =>
  api<void>('/me/notifications/read', { method: 'POST', body: JSON.stringify(ids ? { ids } : {}) })

export const fetchNotificationPrefs = () => api<NotificationPrefsDto>('/me/notification-prefs')

/** 보낸 종류만 바꾼다. 응답은 바뀐 뒤의 전체 설정. */
export const updateNotificationPrefs = (prefs: NotificationPref[]) =>
  api<NotificationPrefsDto>('/me/notification-prefs', { method: 'PUT', body: JSON.stringify({ prefs }) })
