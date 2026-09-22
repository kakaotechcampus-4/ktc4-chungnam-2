import { useQuery } from '@tanstack/react-query'
import type { components } from '@pingo/contracts/src/types/api'

import { api } from '@/api'

export type Pin = components['schemas']['Pin']

/** 목 서버 시드 지도. 지도 선택·초대(#4)가 붙으면 라우트 파라미터로 바뀐다. */
export const MAP_ID = 'map_1'

/**
 * 지도 탭의 핀 목록. 마커(#20)·목록(#19)·상세(#21)가 전부 같은 데이터를 보므로 훅 하나로 모은다.
 * 컴포넌트마다 useQuery 를 따로 쓰면 queryKey 가 어긋나는 순간 같은 화면에서
 * 마커와 목록이 서로 다른 핀을 보여준다.
 *
 * 필터(#18)가 붙으면 queryKey 에 필터 값을 더하고 쿼리스트링을 붙인다 — 그때 이 훅만 고치면 된다.
 */
export function usePins() {
  return useQuery({
    queryKey: ['pins', MAP_ID],
    queryFn: () => api<Pin[]>(`/maps/${MAP_ID}/pins`),
  })
}
