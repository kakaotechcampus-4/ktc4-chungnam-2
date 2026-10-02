import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { deleteReaction, fetchPins, fetchReactions, putReaction } from './api'
import { withMyReaction, type Pin, type ReactionRequest } from './model'

export const pinKeys = {
  list: (mapId: string) => ['pins', mapId] as const,
  reactions: (pinId: string) => ['pins', 'reactions', pinId] as const,
}

/**
 * 지도 탭의 핀 목록. 마커(#20)·목록(#19)·상세(#21)가 전부 같은 데이터를 보므로 훅 하나로 모은다.
 * 컴포넌트마다 useQuery 를 따로 쓰면 queryKey 가 어긋나는 순간 같은 화면에서
 * 마커와 목록이 서로 다른 핀을 보여준다.
 *
 * 필터(#18)가 붙으면 pinKeys.list 에 필터 값을 더하고 쿼리스트링을 붙인다 — 그때 이 파일만 고치면 된다.
 */
export function usePinsQuery(mapId: string) {
  return useQuery<Pin[]>({
    queryKey: pinKeys.list(mapId),
    queryFn: () => fetchPins(mapId),
  })
}

/** 핀 상세 「구성원 의견」. 반응한 구성원만 온다. */
export function useReactionsQuery(pinId: string) {
  return useQuery({ queryKey: pinKeys.reactions(pinId), queryFn: () => fetchReactions(pinId) })
}

/**
 * 내 의견 등록·바꾸기·취소. 성공하면 핀 목록 캐시에 바로 반영하고(withMyReaction) 의견 목록은 다시 받는다.
 * 실패를 조용히 삼키지 않는다 — 부르는 쪽이 토스트로 알린다.
 */
export function useMyReactionMutation(mapId: string, pin: Pin) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: ReactionRequest | null) =>
      body ? putReaction(pin.id, body) : deleteReaction(pin.id).then(() => null),
    onSuccess: (reaction) => {
      queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) =>
        pins?.map((p) => (p.id === pin.id ? withMyReaction(p, reaction) : p)),
      )
      void queryClient.invalidateQueries({ queryKey: pinKeys.reactions(pin.id) })
    },
  })
}
