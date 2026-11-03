import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { pinKeys } from '@/features/map/queries'

import { addToShortlist, exportShortlist, fetchShortlist, removeFromShortlist } from './api'
import { sortItems, type ExportFormat } from './model'

export const shortlistKeys = {
  list: (mapId: string) => ['shortlist', mapId] as const,
}

export function useShortlistQuery(mapId: string) {
  return useQuery({ queryKey: shortlistKeys.list(mapId), queryFn: () => fetchShortlist(mapId), select: sortItems })
}

/** 넣고 빼면 핀 종류(확정 ↔ 원래)가 바뀌므로 핀 목록도 다시 받는다. */
function useRefreshAfterChange(mapId: string) {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({ queryKey: pinKeys.list(mapId) })
    void queryClient.invalidateQueries({ queryKey: shortlistKeys.list(mapId) })
  }
}

/** 「확정 리스트에 넣기」. */
export function useAddToShortlistMutation(mapId: string) {
  const refresh = useRefreshAfterChange(mapId)
  return useMutation({ mutationFn: (pinId: string) => addToShortlist(mapId, pinId), onSuccess: refresh })
}

/** 「빼기」·「확정 해제」 — 핀을 지우는 게 아니라 확정만 푼다. */
export function useRemoveFromShortlistMutation(mapId: string) {
  const refresh = useRefreshAfterChange(mapId)
  return useMutation({ mutationFn: (itemId: string) => removeFromShortlist(itemId), onSuccess: refresh })
}

/**
 * 확정 리스트 파일 받기(#484). 캐시하지 않는다 — 누를 때마다 지금 리스트로 받는다.
 * 복사는 받기가 끝나기 전에 클립보드 쓰기를 시작해야 해서(Safari 사용자 동작 제한) mutation 이 아니라 Promise 를 돌려준다.
 */
export function useShortlistExport(mapId: string) {
  return useCallback((format: ExportFormat) => exportShortlist(mapId, format), [mapId])
}
