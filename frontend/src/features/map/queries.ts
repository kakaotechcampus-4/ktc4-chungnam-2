import { useCallback, useMemo } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { createPin, deletePin, deleteReaction, fetchCounts, fetchPins, fetchReactions, fetchReasonChips, putReaction, resolvePin, updatePin } from './api'
import { useLivePlaceStore, withLivePlace } from './livePlaces'
import { withMyReaction, type Pin, type PinCategory, type PinCreateRequest, type PinResolveRequest, type PinUpdateRequest, type ReactionRequest } from './model'

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

/**
 * 핀 삭제(구성원 누구나). 목록 캐시에서 바로 빼고, 같이 달라지는 집계·확정 리스트·추천 준비 상태는 다시 받는다.
 * 확정 리스트의 항목은 서버가 핀과 함께 지운다.
 */
export function useDeletePinMutation(mapId: string, pinId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => deletePin(pinId),
    onSuccess: () => {
      queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) => pins?.filter((p) => p.id !== pinId))
      void queryClient.invalidateQueries({ queryKey: pinKeys.counts(mapId) })
      void queryClient.invalidateQueries({ queryKey: ['shortlist', mapId] })
      void queryClient.invalidateQueries({ queryKey: ['recommend', mapId] })
    },
  })
}

/**
 * 핀 메모·분류 수정(#466). 목록의 그 핀만 응답으로 바로 바꾼다. 확정 리스트·집계·추천 준비는
 * 내게도 오는 pin.updated를 받아 realtime의 표(refetchTable)대로 다시 받는다 — 다시 받을 목록을 여기에 또 적지 않는다.
 */
export function useUpdatePinMutation(mapId: string, pinId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: PinUpdateRequest) => updatePin(pinId, body),
    onSuccess: (pin) => queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) => pins?.map((p) => (p.id === pin.id ? pin : p))),
  })
}

/**
 * 실시간 핀 승격(#777). 화면이 카카오 SDK로 위치를 찾은 순간 한 번 부른다(useLivePinResolver).
 * 짝이 있으면(source=db) 핀 목록의 그 핀을 응답으로 바꾸고, 핀을 따로 들고 있는 확정 리스트는 다시 받는다 —
 * 그래야 확정 탭 이름과 동선 대상이 바뀐다. 다른 구성원은 pin.updated로 받는다. 짝이 없으면(source=live) 그대로 둔다.
 *
 * 사용자가 누른 게 아니라 화면이 알아서 부르는 요청이라 실패를 알리지 않는다. 409 PIN_DUPLICATE(같은 장소 핀이 이미 있음)도,
 * 네트워크 실패도 핀은 실시간 핀으로 남고, 다시 시도하지 않는다 — 다음에 지도를 열 때 다시 찾고 다시 부른다.
 */
export function useResolveLivePin(mapId: string) {
  const queryClient = useQueryClient()
  return useCallback(
    (pinId: string, hint: PinResolveRequest) => {
      resolvePin(pinId, hint)
        .then((pin) => {
          if (pin.source !== 'db') return
          queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) => pins?.map((p) => (p.id === pin.id ? pin : p)))
          void queryClient.invalidateQueries({ queryKey: ['shortlist', mapId] })
        })
        .catch(() => undefined)
    },
    [mapId, queryClient],
  )
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
