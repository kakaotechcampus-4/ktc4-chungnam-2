import { useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { pinKeys } from '@/features/map/queries'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'

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
  // 다시 받기를 기다린다 — mutation 이 그동안 pending 이라 버튼이 옛 상태로 다시 눌리지 않는다.
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: pinKeys.list(mapId) }),
      queryClient.invalidateQueries({ queryKey: shortlistKeys.list(mapId) }),
    ])
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
 * 확정 해제. 확정 탭의 「빼기」와 핀 상세의 「✓ 확정됨」이 같이 쓴다.
 * 확정 탭은 줄이 사라져서 「되돌리기」 토스트를 띄우고, 핀 상세는 버튼이 그대로 남아 다시 누르면 되므로 띄우지 않는다(undo: false).
 * 핀만 알면 되도록 확정 리스트에서 그 핀의 항목 id를 찾는다.
 */
export function useUnconfirm(mapId: string) {
  const remove = useRemoveFromShortlistMutation(mapId)
  const add = useAddToShortlistMutation(mapId)
  const items = useShortlistQuery(mapId).data
  const unconfirm = (pin: { id: string; place_name?: string | null }, { undo = true } = {}) => {
    // 줄은 다시 받을 때까지 남아 있어 두 번 누를 수 있다. 두 번째가 404로 실패 토스트를 띄우고 첫 번째의 「되돌리기」를 지웠다.
    if (remove.isPending) return
    const item = items?.find((i) => i.pin.id === pin.id)
    if (!item) return showToast('확정 리스트를 불러오는 중이에요. 잠시 뒤에 다시 눌러 주세요')
    const name = pin.place_name ?? '이 장소'
    remove.mutate(item.id, {
      onSuccess: () =>
        undo &&
        showToast(`${name}${josa(name, '을', '를')} 확정 리스트에서 뺐어요`, {
          label: '되돌리기',
          onClick: () => add.mutate(pin.id, { onError: () => showToast('되돌리지 못했어요') }),
        }),
      onError: () => showToast('확정 리스트에서 빼지 못했어요'),
    })
  }
  return { unconfirm, isPending: remove.isPending }
}

/**
 * 확정 리스트 파일 받기(#484). 캐시하지 않는다 — 누를 때마다 지금 리스트로 받는다.
 * 복사는 받기가 끝나기 전에 클립보드 쓰기를 시작해야 해서(Safari 사용자 동작 제한) mutation 이 아니라 Promise 를 돌려준다.
 */
export function useShortlistExport(mapId: string) {
  return useCallback((format: ExportFormat) => exportShortlist(mapId, format), [mapId])
}
