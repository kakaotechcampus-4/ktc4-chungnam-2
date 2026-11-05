import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

/** 고른 핀 id 를 담는 주소 쿼리 이름. 다른 탭에서 핀 카드를 열 때(핑고 조언 open_pin)도 이 이름으로 간다. */
export const PIN_PARAM = 'pin'

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
    (pinId: string | null) => {
      const next = new URLSearchParams(params)
      if (pinId) next.set(PIN_PARAM, pinId)
      else next.delete(PIN_PARAM)
      setParams(next)
    },
    [params, setParams],
  )

  return { selectedPinId: params.get(PIN_PARAM), selectPin }
}
