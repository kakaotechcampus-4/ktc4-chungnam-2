import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useMeQuery } from '@/features/auth/queries'

import { acceptInvite, createInvite, createMap, fetchMap, fetchMaps, fetchMembers } from './api'
import { toMapHeaderView, toMapView, toMemberView, type MapCreateRequest } from './model'

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
