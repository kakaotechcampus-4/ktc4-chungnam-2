import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useMeQuery } from '@/features/auth/queries'

import { acceptInvite, createInvite, createMap, deleteMap, fetchInviteSummary, fetchMap, fetchMaps, fetchMembers, leaveMap } from './api'
import { inviteProblem, toInviteView, toMapHeaderView, toMapView, toMemberView, type MapCreateRequest } from './model'

export const mapKeys = {
  all: ['maps'] as const,
  detail: (mapId: string) => ['maps', mapId] as const,
  members: (mapId: string) => ['maps', mapId, 'members'] as const,
}

/** 내 지도 목록 (#24). */
export function useMapsQuery() {
  return useQuery({
    queryKey: mapKeys.all,
    queryFn: fetchMaps,
    select: (maps) => maps.map(toMapView),
  })
}

/** 지도가 하나 늘었으니 목록을 다시 받는다. 성공하면 만들어진 지도의 id 를 돌려준다. */
export function useCreateMapMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: MapCreateRequest) => createMap(body),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: mapKeys.all }),
  })
}

/**
 * 지도 삭제·나가기 뒤엔 그 지도의 캐시를 버리고 목록을 다시 받는다 — 지워진 지도의 핀이 화면에 남지 않게.
 * 어느 쪽이든 이 지도는 더 이상 내 지도가 아니다.
 */
function useLeaveCleanup() {
  const queryClient = useQueryClient()
  return (mapId: string) => {
    queryClient.removeQueries({ queryKey: mapKeys.detail(mapId) })
    queryClient.removeQueries({ queryKey: ['pins', mapId] })
    queryClient.removeQueries({ queryKey: ['shortlist', mapId] })
    void queryClient.invalidateQueries({ queryKey: mapKeys.all, exact: true })
  }
}

export function useDeleteMapMutation(mapId: string) {
  const cleanup = useLeaveCleanup()
  return useMutation({ mutationFn: () => deleteMap(mapId), onSuccess: () => cleanup(mapId) })
}

export function useLeaveMapMutation(mapId: string) {
  const cleanup = useLeaveCleanup()
  return useMutation({ mutationFn: () => leaveMap(mapId), onSuccess: () => cleanup(mapId) })
}

export function useAcceptInviteMutation(token: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => acceptInvite(token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: mapKeys.all }),
  })
}

export function useMapQuery(mapId: string) {
  return useQuery({
    queryKey: mapKeys.detail(mapId),
    queryFn: () => fetchMap(mapId),
    select: toMapHeaderView,
  })
}

/** 내 이름 옆 "(나)" 표시 때문에 로그인 정보와 같이 본다. */
export function useMembersQuery(mapId: string) {
  const myUserId = useMeQuery().data?.id
  return useQuery({
    queryKey: mapKeys.members(mapId),
    queryFn: () => fetchMembers(mapId),
    select: (members) => members.map((m) => toMemberView(m, myUserId)),
  })
}

/** 초대 링크는 열 때마다 새로 받지 않는다 — 프로필 모달을 여닫을 때마다 토큰이 늘어나지 않게. */
export function useInviteQuery(mapId: string, enabled: boolean) {
  return useQuery({
    queryKey: ['maps', mapId, 'invite'],
    queryFn: () => createInvite(mapId),
    enabled,
    staleTime: Infinity,
  })
}

/** 초대 요약(C-1/C-2). 로그인 없이 부를 수 있다. 만료·없는 링크는 다시 물어도 같으니 재시도하지 않는다. */
export function useInviteSummaryQuery(token: string) {
  return useQuery({
    queryKey: ['invites', token],
    queryFn: () => fetchInviteSummary(token),
    select: toInviteView,
    retry: (count, err) => !inviteProblem(err) && count < 1,
  })
}

/** 계정 시트의 "지도마다 링크 복사". 누를 때 만든다 — 목록을 열 때마다 지도 수만큼 링크를 만들지 않게. */
export function useCreateInviteMutation() {
  return useMutation({ mutationFn: (mapId: string) => createInvite(mapId) })
}
