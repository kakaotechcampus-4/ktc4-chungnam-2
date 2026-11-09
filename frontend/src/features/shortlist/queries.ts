import { useCallback, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { Pin } from '@/features/map/model'
import { pinKeys } from '@/features/map/queries'
import { showToast } from '@/features/shell/toast'
import { josa } from '@/ui/josa'

import { addToShortlist, exportShortlist, fetchShortlist, removeFromShortlist } from './api'
import { sortItems, type ExportFormat, type ShortlistItemDto } from './model'

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

/**
 * 「확정 리스트에 넣기」. 누르는 순간 그 핀을 확정으로 바꿔 보인다(#1676, 낙관적 UI) — 버튼과 지도 핀 색이 응답과 다시 받기를 기다리지 않는다.
 * 넣으면 확정이라는 건 정의라 화면이 짐작하는 게 아니다. 실패하면 그 핀의 종류만 되돌린다(목록 전체를 옛 사진으로 덮으면 그사이 실시간으로 온 변경까지 지운다).
 */
export function useAddToShortlistMutation(mapId: string) {
  const queryClient = useQueryClient()
  const refresh = useRefreshAfterChange(mapId)
  const setKind = (pinId: string, kind: Pin['kind']) =>
    queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) => pins?.map((p) => (p.id === pinId ? { ...p, kind } : p)))
  return useMutation({
    mutationFn: (pinId: string) => addToShortlist(mapId, pinId),
    onMutate: async (pinId) => {
      await queryClient.cancelQueries({ queryKey: pinKeys.list(mapId) })
      const kind = queryClient.getQueryData<Pin[]>(pinKeys.list(mapId))?.find((p) => p.id === pinId)?.kind
      setKind(pinId, '확정')
      return { kind }
    },
    onError: (_err, pinId, ctx) => {
      if (ctx?.kind) setKind(pinId, ctx.kind)
    },
    onSuccess: refresh,
  })
}

/**
 * 「빼기」·「확정 해제」 — 핀을 지우는 게 아니라 확정만 푼다. 누르는 순간 확정 리스트에서 그 줄을 뺀다(#1676) —
 * 다시 받을 때까지 줄이 남아 두 번 누를 수 있었다. 핀 종류는 짐작하지 않는다 — 서버가 핀의 출처로 되돌리는데(pins.core.kind_after_unconfirm)
 * 화면이 받는 핀에는 출처가 없어서, 핀 색은 다시 받은 뒤에 바뀐다. 버튼은 `useUnconfirm`의 `isPending`으로 먼저 바뀐다.
 */
export function useRemoveFromShortlistMutation(mapId: string) {
  const queryClient = useQueryClient()
  const refresh = useRefreshAfterChange(mapId)
  const key = shortlistKeys.list(mapId)
  return useMutation({
    mutationFn: (itemId: string) => removeFromShortlist(itemId),
    onMutate: async (itemId) => {
      await queryClient.cancelQueries({ queryKey: key })
      const item = queryClient.getQueryData<ShortlistItemDto[]>(key)?.find((i) => i.id === itemId)
      queryClient.setQueryData<ShortlistItemDto[]>(key, (items) => items?.filter((i) => i.id !== itemId))
      return { item }
    },
    onError: (_err, _itemId, ctx) => {
      const item = ctx?.item
      if (item) queryClient.setQueryData<ShortlistItemDto[]>(key, (items) => (items && !items.some((i) => i.id === item.id) ? [...items, item] : items))
    },
    onSuccess: refresh,
  })
}

/**
 * 확정 해제. 확정 탭의 「빼기」와 핀 상세의 「✓ 확정됨」이 같이 쓴다.
 * 둘 다 「되돌리기」 토스트를 띄운다 — 넣을 때 토스트로 알리니 뺄 때도 같은 자리에서 알린다(#1576).
 * 핀만 알면 되도록 확정 리스트에서 그 핀의 항목 id를 찾는다.
 */
export function useUnconfirm(mapId: string) {
  const remove = useRemoveFromShortlistMutation(mapId)
  const add = useAddToShortlistMutation(mapId)
  const items = useShortlistQuery(mapId).data
  const [removingPinId, setRemoving] = useState<string>()
  const unconfirm = (pin: { id: string; place_name?: string | null }) => {
    // 빼는 중에 또 누르면 무시한다 — 두 번째가 404로 실패 토스트를 띄우고 첫 번째의 「되돌리기」를 지웠다. 줄은 누르는 순간 빠진다(#1676).
    const item = items?.find((i) => i.pin.id === pin.id)
    if (!item) return showToast('확정 리스트를 불러오는 중이에요. 잠시 뒤에 다시 눌러 주세요')
    if (remove.isPending && remove.variables === item.id) return
    const name = pin.place_name ?? '이 장소'
    setRemoving(pin.id)
    remove.mutate(item.id, {
      onSettled: () => setRemoving(undefined),
      onSuccess: () =>
        showToast(`${name}${josa(name, '을', '를')} 확정 리스트에서 뺐어요`, {
          label: '되돌리기',
          onClick: () => add.mutate(pin.id, { onError: () => showToast('되돌리지 못했어요') }),
        }),
      onError: () => showToast('확정 리스트에서 빼지 못했어요'),
    })
  }
  /** 지금 빼는 중인 핀 — 핀 상세 버튼이 응답 전에 「확정 리스트에 넣기」로 바뀐다. 줄은 낙관적으로 이미 빠져서 목록에서 찾지 못해 따로 기억한다. */
  return { unconfirm, isPending: remove.isPending, removingPinId }
}

/**
 * 확정 리스트 파일 받기(#484). 캐시하지 않는다 — 누를 때마다 지금 리스트로 받는다.
 * 복사는 받기가 끝나기 전에 클립보드 쓰기를 시작해야 해서(Safari 사용자 동작 제한) mutation 이 아니라 Promise 를 돌려준다.
 */
export function useShortlistExport(mapId: string) {
  return useCallback((format: ExportFormat) => exportShortlist(mapId, format), [mapId])
}

