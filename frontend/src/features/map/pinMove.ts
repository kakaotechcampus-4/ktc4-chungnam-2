import type { QueryClient } from '@tanstack/react-query'

import { distanceM, searchPinRequest, type PlaceSearchResultDto } from '@/features/search/model'

import { createPin, deletePin, updatePin } from './api'
import type { Pin } from './model'
import { pinKeys, restoreInto } from './queries'

/**
 * 핀 끌어 옮기기(#1549). 옮기기는 새 장소로 핀을 새로 만들고 옛 핀을 휴지통에 넣는 일이다.
 * 의견(좋음, 반대 사유)은 옛 장소에 대한 말이라 옛 핀과 함께 휴지통에 남는다. 서버는 고치지 않는다.
 */

/** 옮길 수 있는 핀인가. 아니면 왜 안 되는지 알림 문장을 돌려준다(그런 핀도 휴지통에는 놓을 수 있다). */
export function moveBlockedReason(pin: Pin): string | null {
  if (pin.kind === '확정') return '확정 핀은 옮길 수 없어요. 옮기면 확정이 풀려요'
  if (pin.kind === 'AI추천') return 'AI 추천 핀은 옮길 수 없어요. 추천 이유가 그 장소 기준이에요'
  if (!pin.permissions.can_edit) return '내가 찍은 핀만 옮길 수 있어요'
  return null
}

/** 지금 핀이 있는 장소와 같은 곳(이름이 같고 50m 안)은 옮길 곳에서 뺀다. */
const SAME_M = 50
export function moveTargets(pin: Pin, places: PlaceSearchResultDto[]): PlaceSearchResultDto[] {
  return places.filter(
    (p) => p.pinnable !== false && !(pin.place_name === p.place_name && pin.lat != null && pin.lng != null && distanceM({ lat: pin.lat, lng: pin.lng }, p) < SAME_M),
  )
}

function swapInList(queryClient: QueryClient, mapId: string, remove: string, add?: Pin) {
  queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) => pins && [...pins.filter((p) => p.id !== remove && p.id !== add?.id), ...(add ? [add] : [])])
  void queryClient.invalidateQueries({ queryKey: pinKeys.counts(mapId) })
  void queryClient.invalidateQueries({ queryKey: pinKeys.trash(mapId) })
  void queryClient.invalidateQueries({ queryKey: ['recommend', mapId] })
}

/**
 * 새 핀을 먼저 만들고(메모는 옛 핀 그대로), 성공하면 옛 핀을 지운다. 중간에 실패하면 만든 새 핀을 지워 아무것도 바뀌지 않게 한다.
 * 만들기가 실패하면(409 PIN_DUPLICATE 등) 그 오류를 그대로 던진다 — 부르는 쪽이 문장으로 알린다.
 */
export async function movePin(queryClient: QueryClient, mapId: string, pin: Pin, place: PlaceSearchResultDto): Promise<Pin> {
  const req = searchPinRequest(place)
  if (!req) throw new Error('옮길 장소의 분류를 몰라요')
  let created = await createPin(mapId, req)
  try {
    if (pin.memo) created = await updatePin(created.id, { memo: pin.memo })
    await deletePin(pin.id)
  } catch (err) {
    await deletePin(created.id).catch(() => undefined)
    throw err
  }
  swapInList(queryClient, mapId, pin.id, created)
  return created
}

/** 옮기기 되돌리기: 새 핀을 지우고 옛 핀을 되살린다(의견도 같이 돌아온다). */
export async function undoMove(queryClient: QueryClient, mapId: string, created: Pin, old: Pin): Promise<void> {
  await deletePin(created.id)
  swapInList(queryClient, mapId, created.id)
  await restoreInto(queryClient, mapId, old.id)
}
