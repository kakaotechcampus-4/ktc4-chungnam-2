import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { showToast } from '@/features/shell/toast'

import { fetchNotificationPrefs, fetchNotifications, markNotificationsRead, updateNotificationPrefs } from './api'
import type { NotificationPref, NotificationPrefsDto } from './model'

export const notificationKeys = {
  list: ['notifications'] as const,
  prefs: ['notifications', 'prefs'] as const,
}

/**
 * 알림함과 종 배지가 같이 본다(배지는 첫 페이지의 unread_count). 실시간 푸시가 없어서
 * 앱을 열 때·화면에 포커스가 돌아올 때·알림함을 열 때 다시 받는다(api-spec GET /me/notifications).
 * 앱 전체 기본값은 포커스 때 다시 받지 않아서 여기서만 켠다.
 */
export function useNotificationsQuery() {
  return useInfiniteQuery({
    queryKey: notificationKeys.list,
    queryFn: ({ pageParam }) => fetchNotifications(pageParam),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_before,
    refetchOnWindowFocus: true,
  })
}

/** 읽음 처리 뒤 목록과 배지를 다시 받는다. ids를 빼면 전부 읽음. */
export function useMarkReadMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (ids?: string[]) => markNotificationsRead(ids),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: notificationKeys.list, exact: true }),
    // 알림을 누르면 화면을 옮기므로 부르는 쪽이 사라져 있을 수 있다 — 실패 알림은 여기서 한다.
    onError: () => showToast('알림을 읽음으로 바꾸지 못했어요'),
  })
}

export function useNotificationPrefsQuery() {
  return useQuery({ queryKey: notificationKeys.prefs, queryFn: fetchNotificationPrefs, select: (d) => d.prefs })
}

/** 한 종류를 켜고 끈다. 응답이 전체 설정이라 그대로 캐시에 넣는다. */
export function useUpdatePrefMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (pref: NotificationPref) => updateNotificationPrefs([pref]),
    onSuccess: (prefs) => queryClient.setQueryData<NotificationPrefsDto>(notificationKeys.prefs, prefs),
  })
}
