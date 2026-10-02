import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { acceptInvite, createMap, fetchMaps } from './api'
import { toMapView, type MapCreateRequest } from './model'

export const mapKeys = {
  all: ['maps'] as const,
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
