import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

/** 고른 핀 id 를 담는 주소 쿼리 이름. 다른 탭에서 핀 카드를 열 때(핑고 조언 open_pin)도 이 이름으로 간다. */
export const PIN_PARAM = 'pin'
/** 목록 카드의 "✕ 반대"로 열 때만 붙는다 — 상세가 반대를 고른 채로 사유 입력부터 연다(#1696). 핀을 바꾸거나 닫으면 지운다. */
export const REACT_PARAM = 'react'

/**
 * 선택된 핀은 주소에 둔다 (#21 "주소 라우팅 복원").
 *
 * 스토어가 아니라 URL 이 정본인 이유: 상세를 연 채로 주소를 공유하거나 새로고침해도
 * 같은 핀이 다시 열려야 한다. 뒤로가기로 시트가 닫히는 것도 여기서 공짜로 따라온다.
 * 필터(#18)의 "URL 쿼리 동기화"도 같은 자리에 같은 방식으로 붙는다.
 */
export function usePinSelection() {
  const [params, setParams] = useSearchParams()

  const selectPin = useCallback(
    (pinId: string | null, opts?: { against?: boolean }) => {
      const next = new URLSearchParams(params)
      if (pinId) next.set(PIN_PARAM, pinId)
      else next.delete(PIN_PARAM)
      if (pinId && opts?.against) next.set(REACT_PARAM, 'against')
      else next.delete(REACT_PARAM)
      setParams(next)
    },
    [params, setParams],
  )

  return { selectedPinId: params.get(PIN_PARAM), startAgainst: params.get(REACT_PARAM) === 'against', selectPin }
}

/** 겹친 핀 묶음의 핀 id 들(쉼표로 잇는다, #1576). 고른 핀처럼 주소에 둬서 뒤로가기로 목록이 닫히고, 목록에서 연 핀을 닫으면 목록으로 돌아온다. */
export const PIN_GROUP_PARAM = 'pins'

/** 지도에서 누른 겹친 핀 묶음(#1576). 가장 가까이 확대해도 겹쳐서 그 핀들만 목록으로 본다. */
export function usePinGroup() {
  const [params, setParams] = useSearchParams()
  const showGroup = useCallback(
    (pinIds: string[] | null) => {
      const next = new URLSearchParams(params)
      next.delete(PIN_PARAM)
      if (pinIds) next.set(PIN_GROUP_PARAM, pinIds.join(','))
      else next.delete(PIN_GROUP_PARAM)
      setParams(next)
    },
    [params, setParams],
  )
  return { groupIds: params.get(PIN_GROUP_PARAM)?.split(',').filter(Boolean) ?? null, showGroup }
}
