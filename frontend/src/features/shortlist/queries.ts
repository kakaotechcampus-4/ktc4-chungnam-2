import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { pinKeys } from '@/features/map/queries'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'

import { addToShortlist, calculateRoute, exportShortlist, fetchRoute, fetchShortlist, removeFromShortlist, reorderShortlist } from './api'
import { sortItems, type ExportFormat, type ShortlistItemDto } from './model'

export const shortlistKeys = {
  list: (mapId: string) => ['shortlist', mapId] as const,
  route: (mapId: string) => ['shortlist', mapId, 'route'] as const,
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
 * 확정 해제 + 「되돌리기」 토스트. 확정 탭의 「빼기」와 핀 상세의 「✓ 확정됨」이 같이 쓴다.
 * 핀 상세는 핀만 알아서 확정 리스트에서 그 핀의 항목 id를 찾는다.
 */
export function useUnconfirm(mapId: string) {
  const remove = useRemoveFromShortlistMutation(mapId)
  const add = useAddToShortlistMutation(mapId)
  const items = useShortlistQuery(mapId).data
  const unconfirm = (pin: { id: string; place_name?: string | null }) => {
    const item = items?.find((i) => i.pin.id === pin.id)
    if (!item) return showToast('확정 리스트를 불러오는 중이에요. 잠시 뒤에 다시 눌러 주세요')
    const name = pin.place_name ?? '이 장소'
    remove.mutate(item.id, {
      onSuccess: () =>
        showToast(`${name}${josa(name, '을', '를')} 확정 리스트에서 뺐어요`, {
          label: '되돌리기',
          onClick: () => add.mutate(pin.id, { onError: () => showToast('되돌리지 못했어요') }),
        }),
      onError: () => showToast('확정 리스트에서 빼지 못했어요'),
    })
  }
  return { unconfirm, isPending: remove.isPending }
}

/** 끌어서 순서 바꾸기. 놓는 순간 화면을 먼저 바꾸고, 실패하면 되돌린다. */
export function useReorderShortlistMutation(mapId: string) {
  const queryClient = useQueryClient()
  const key = shortlistKeys.list(mapId)
  return useMutation({
    mutationFn: (items: ShortlistItemDto[]) => reorderShortlist(mapId, items.map((i) => i.id)),
    onMutate: async (items) => {
      await queryClient.cancelQueries({ queryKey: key })
      const before = queryClient.getQueryData<ShortlistItemDto[]>(key)
      queryClient.setQueryData(key, items.map((item, i) => ({ ...item, visit_order: i })))
      return { before }
    },
    onError: (_err, _items, ctx) => queryClient.setQueryData(key, ctx?.before),
    onSuccess: (items) => queryClient.setQueryData(key, items),
  })
}

/** 동선 계산. 확정 리스트가 바뀌어도 서버는 다시 계산하지 않아서(#30) 동선 보기가 켜져 있으면 FE 가 다시 부른다. */
export function useRouteMutation(mapId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => calculateRoute(mapId),
    onSuccess: (routes) => queryClient.setQueryData(shortlistKeys.route(mapId), routes),
  })
}

/** 지도에 그릴 동선. 「동선 보기」가 켜졌을 때만 본다. */
export function useRouteQuery(mapId: string, enabled: boolean) {
  return useQuery({ queryKey: shortlistKeys.route(mapId), queryFn: () => fetchRoute(mapId), enabled })
}

/**
 * 확정 리스트 파일 받기(#484). 캐시하지 않는다 — 누를 때마다 지금 리스트로 받는다.
 * 복사는 받기가 끝나기 전에 클립보드 쓰기를 시작해야 해서(Safari 사용자 동작 제한) mutation 이 아니라 Promise 를 돌려준다.
 */
export function useShortlistExport(mapId: string) {
  return useCallback((format: ExportFormat) => exportShortlist(mapId, format), [mapId])
}
