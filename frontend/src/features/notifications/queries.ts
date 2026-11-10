import { useInfiniteQuery, useMutation, useQuery, useQueryClient, type InfiniteData } from '@tanstack/react-query'

import { showToast } from '@/features/shell/toast'

import { fetchNotificationPrefs, fetchNotifications, markNotificationsRead, updateNotificationPrefs } from './api'
import { markReadLocally, type NotificationListDto, type NotificationPref, type NotificationPrefsDto } from './model'

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

/**
 * 읽음 처리. ids를 빼면 전부 읽음. 누르는 순간 그 줄의 점과 종 배지 숫자를 줄인다(#1676, 낙관적 UI) — 알림을 누르면 화면을 옮겨서,
 * 다시 받기를 기다리면 돌아왔을 때 배지가 그대로였다. 끝나면(실패해도) 서버 값으로 다시 받는다 — 실패하면 그게 되돌리기다.
 */
export function useMarkReadMutation() {
  const queryClient = useQueryClient()
  const key = notificationKeys.list
  return useMutation({
    mutationFn: (ids?: string[]) => markNotificationsRead(ids),
    onMutate: async (ids) => {
      await queryClient.cancelQueries({ queryKey: key, exact: true })
      queryClient.setQueryData<InfiniteData<NotificationListDto>>(key, (data) => data && markReadLocally(data, ids))
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: key, exact: true }),
    // 알림을 누르면 화면을 옮기므로 부르는 쪽이 사라져 있을 수 있다 — 실패 알림은 여기서 한다.
    onError: () => showToast('읽음 처리하지 못했어요'),
  })
}

export function useNotificationPrefsQuery() {
  return useQuery({ queryKey: notificationKeys.prefs, queryFn: fetchNotificationPrefs, select: (d) => d.prefs })
}

/** 한 종류를 켜고 끈다. 응답이 전체 설정이라 그대로 캐시에 넣는다. */
export function useUpdatePrefMutation() {
  const queryClient = useQueryClient()
  // 스위치는 누르는 순간 움직인다(#1676) — 응답을 기다리면 손을 뗀 뒤에야 바뀌어 안 눌린 줄 알았다. 실패하면 그 줄만 되돌린다.
  const setPref = (pref: NotificationPref) =>
    queryClient.setQueryData<NotificationPrefsDto>(notificationKeys.prefs, (d) => d && { ...d, prefs: d.prefs.map((p) => (p.type === pref.type ? pref : p)) })
  return useMutation({
    mutationFn: (pref: NotificationPref) => updateNotificationPrefs([pref]),
    onMutate: async (pref) => {
      await queryClient.cancelQueries({ queryKey: notificationKeys.prefs })
      setPref(pref)
    },
    onError: (_err, pref) => setPref({ ...pref, enabled: !pref.enabled }),
    onSuccess: (prefs) => queryClient.setQueryData<NotificationPrefsDto>(notificationKeys.prefs, prefs),
  })
}
