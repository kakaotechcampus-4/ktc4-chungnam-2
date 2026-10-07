import { useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { createPin, deleteReaction, fetchCounts, fetchPins, fetchReactions, fetchReasonChips, putReaction } from './api'
import { useLivePlaceStore, withLivePlace } from './livePlaces'
import { withMyReaction, type Pin, type PinCategory, type PinCreateRequest, type ReactionRequest } from './model'

export const pinKeys = {
  list: (mapId: string) => ['pins', mapId] as const,
  reactions: (pinId: string) => ['pins', 'reactions', pinId] as const,
  counts: (mapId: string) => ['pins', mapId, 'counts'] as const,
  chips: (category: PinCategory) => ['reason-chips', category] as const,
}

/**
 * 지도 탭의 핀 목록. 마커(#20)·목록(#19)·상세(#21)가 전부 같은 데이터를 보므로 훅 하나로 모은다.
 * 컴포넌트마다 useQuery 를 따로 쓰면 queryKey 가 어긋나는 순간 같은 화면에서
 * 마커와 목록이 서로 다른 핀을 보여준다.
 *
 * 필터(#18)가 붙으면 pinKeys.list 에 필터 값을 더하고 쿼리스트링을 붙인다 — 그때 이 파일만 고치면 된다.
 */
export function usePinsQuery(mapId: string) {
  const query = useQuery<Pin[]>({
    queryKey: pinKeys.list(mapId),
    queryFn: () => fetchPins(mapId),
  })
  // 실시간 핀(#382)은 서버에 이름·좌표가 없다. 화면이 다시 찾은 값을 여기서 한 번 얹어 마커·목록·상세가 같은 핀을 보게 한다.
  const places = useLivePlaceStore((s) => s.places)
  const data = useMemo(() => query.data?.map((p) => withLivePlace(p, places)), [query.data, places])
  return { ...query, data }
}

/** 핀 상세 「구성원 의견」. 반응한 구성원만 온다. */
export function useReactionsQuery(pinId: string) {
  return useQuery({ queryKey: pinKeys.reactions(pinId), queryFn: () => fetchReactions(pinId) })
}

/** 「2/4명이 의견을 남겼어요」. 누가 의견을 남기면(내 것은 mutation, 남의 것은 SSE) 다시 받는다. */
export function useCountsQuery(mapId: string) {
  return useQuery({ queryKey: pinKeys.counts(mapId), queryFn: () => fetchCounts(mapId) })
}

/** 반대 사유 칩. 고정 목록이라(api-spec) 한 번 받으면 다시 묻지 않는다. */
export function useReasonChipsQuery(category: PinCategory) {
  return useQuery({ queryKey: pinKeys.chips(category), queryFn: () => fetchReasonChips(category), staleTime: Infinity })
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
      void queryClient.invalidateQueries({ queryKey: pinKeys.counts(mapId) })
    },
  })
}

/** 검색 결과로 핀 찍기(v1 유일한 경로, #191). 만든 핀을 목록 끝에 바로 넣는다 — SSE 로 같은 핀이 와도 id 로 덮어쓴다. */
export function useCreatePinMutation(mapId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: PinCreateRequest) => createPin(mapId, body),
    onSuccess: (pin) =>
      queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) =>
        pins && (pins.some((p) => p.id === pin.id) ? pins : [...pins, pin]),
      ),
  })
}
