import { useMutation, useQueryClient } from '@tanstack/react-query'

import { pinKeys } from '@/features/map/queries'

import { addToShortlist } from './api'

export const shortlistKeys = {
  list: (mapId: string) => ['shortlist', mapId] as const,
}

/** 「확정 리스트에 넣기」. 넣으면 핀 종류가 확정으로 바뀌므로 핀 목록도 다시 받는다. */
export function useAddToShortlistMutation(mapId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (pinId: string) => addToShortlist(mapId, pinId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: pinKeys.list(mapId) })
      void queryClient.invalidateQueries({ queryKey: shortlistKeys.list(mapId) })
    },
  })
}
