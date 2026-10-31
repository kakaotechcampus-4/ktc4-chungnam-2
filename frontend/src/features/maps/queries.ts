import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { useMeQuery } from '@/features/auth/queries'

import { acceptInvite, createInvite, createMap, deleteMap, fetchInvites, fetchInviteSummary, fetchMap, fetchMaps, fetchMembers, fetchTrash, leaveMap, restoreMap, revokeInvite, transferOwner, updateMap } from './api'
import { ApiError } from '@/api'

import { inviteProblem, toInviteRowView, toInviteView, toMapHeaderView, toMapListView, toMemberView, toTrashView, type InviteDto, type MapCreateRequest, type MapDto, type MapUpdateRequest } from './model'

export const mapKeys = {
  all: ['maps'] as const,
  detail: (mapId: string) => ['maps', mapId] as const,
  members: (mapId: string) => ['maps', mapId, 'members'] as const,
  trash: ['maps', 'trash'] as const,
  // 지도 상세 키 아래라 구성원이 들어오면(member.joined) 참여 수도 같이 다시 받는다.
  invites: (mapId: string) => ['maps', mapId, 'invites'] as const,
}

/** 내 지도 목록과 상한 (#24, #623). */
export function useMapsQuery() {
  return useQuery({
    queryKey: mapKeys.all,
    queryFn: fetchMaps,
    select: toMapListView,
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
 * 지도 수정(방장, #465). 상세만 응답으로 바로 바꾼다. 내 지도 목록은 내게도 오는 map.updated를 받아
 * realtime의 표(refetchTable)대로 다시 받는다.
 */
export function useUpdateMapMutation(mapId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: MapUpdateRequest) => updateMap(mapId, body),
    onSuccess: (map) => queryClient.setQueryData<MapDto>(mapKeys.detail(mapId), map),
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

/** 지운 지도는 휴지통으로 간다(#464) — 휴지통도 다시 받는다. */
export function useDeleteMapMutation(mapId: string) {
  const cleanup = useLeaveCleanup()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deleteMap(mapId),
    onSuccess: () => {
      cleanup(mapId)
      void queryClient.invalidateQueries({ queryKey: mapKeys.trash })
    },
  })
}

/** 휴지통(#464). 내 지도 목록에서 비어 있지 않을 때만 입구를 보인다. */
export function useTrashQuery() {
  return useQuery({ queryKey: mapKeys.trash, queryFn: fetchTrash, select: toTrashView })
}

/** 복구하면 내 지도 목록과 휴지통이 같이 바뀐다. */
export function useRestoreMapMutation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: restoreMap,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: mapKeys.all, exact: true })
      void queryClient.invalidateQueries({ queryKey: mapKeys.trash })
    },
  })
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

/** 켜진 초대 링크 목록(방장, #467). 목록을 펼쳤을 때만 받는다. */
export function useInvitesQuery(mapId: string, enabled: boolean) {
  return useQuery({
    queryKey: mapKeys.invites(mapId),
    queryFn: () => fetchInvites(mapId),
    select: (invites) => invites.map(toInviteRowView),
    enabled,
  })
}

/** 초대 링크 끄기. 이벤트가 없어 목록에서 바로 뺀다. */
export function useRevokeInviteMutation(mapId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: revokeInvite,
    onSuccess: (_, token) => queryClient.setQueryData<InviteDto[]>(mapKeys.invites(mapId), (list) => list?.filter((i) => i.token !== token)),
  })
}

/**
 * 방장 넘기기(#468). 지도 상세만 응답으로 바로 바꾼다. 구성원 목록(방장 표시)은 내게도 오는 owner.changed를 받아
 * realtime의 표(refetchTable)대로 다시 받는다. 고른 사람이 그사이 나갔으면(OWNER_TARGET_INVALID) 구성원을 다시 받아 고르게 한다(docs/errors.md).
 */
export function useTransferOwnerMutation(mapId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (userId: string) => transferOwner(mapId, { user_id: userId }),
    onSuccess: (map) => queryClient.setQueryData<MapDto>(mapKeys.detail(mapId), map),
    onError: (err) => {
      if (err instanceof ApiError && err.code === 'OWNER_TARGET_INVALID') void queryClient.invalidateQueries({ queryKey: mapKeys.members(mapId) })
    },
  })
}
