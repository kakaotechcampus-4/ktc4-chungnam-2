import { useNavigate } from 'react-router'

import { useCourseViewStore } from '@/features/course/courseMapStore'
import { usePinsQuery } from '@/features/map/queries'
import { PIN_PARAM } from '@/features/map/usePinSelection'
import { useMapQuery } from '@/features/maps/queries'
import { useAiStore } from '@/features/recommend/aiStore'
import { useSearchStore } from '@/features/search/searchStore'
import { useSheetStore } from '@/features/shell/sheetStore'
import { showToast } from '@/features/shell/toast'
import { openRoute } from '@/features/shortlist/routeStore'

import type { AgentActionDto } from './model'

/** 기존 동작이 막히면(준비 안 됨, 상한 등) 같은 문구로 알린다(agent-v2 16.3). */
export const CHANGED = '상황이 바뀌었어요'

/** 추천 탭(Readiness)·AI 코스 탭(CourseBody)이 이 값을 보고 손으로 누를 때와 같은 실행을 한 번 시작한다. 추천은 값이 카테고리다. */
export const START_PARAM = 'start'

/**
 * 제안 버튼의 동작 — 사람이 원래 하던 동작의 지름길이다(agent-v2 16.3 표). 근거 확인·⓪·재시도 상한은 손으로 할 때와 똑같이 걸린다.
 * widen_radius·open_evidence 는 추천 막힘 조언(#589)의 버튼이라 여기서는 다루지 않는다.
 */
export function useRunAgentAction(mapId: string) {
  const navigate = useNavigate()
  const center = useMapQuery(mapId).data?.regionCenter ?? null
  const pins = usePinsQuery(mapId).data
  return (action: AgentActionDto) => {
    const { category, unseen_only, pin_ids } = action.params
    const sheet = useSheetStore.getState()
    // 넓은 화면에서 패널이 접혀 있으면 결과를 볼 곳이 없다.
    sheet.setPanelOpen(true)
    switch (action.type) {
      case 'open_recommend':
        if (!category) return showToast(CHANGED)
        // 보고 있던 결과 대신 새 추천을 시작한다 — 탭이 준비 화면에서 이 카테고리로 시작한다.
        useAiStore.getState().setRun(mapId, undefined)
        navigate(`/maps/${mapId}/recommend?${new URLSearchParams({ [START_PARAM]: category })}`)
        return
      case 'show_pins': {
        // ponytail: pin_ids 는 쓰지 않는다 — 카테고리와 「내가 아직 안 남김」 필터로 같은 핀이 보인다. 핀만 콕 집을 일이 생기면 필터에 더한다.
        const filters = new URLSearchParams()
        if (category) filters.set('category', category)
        if (unseen_only) filters.set('opinion', 'none')
        sheet.setStage('map', 2)
        navigate(`/maps/${mapId}?${filters}`)
        return
      }
      case 'search_place':
        navigate(`/maps/${mapId}`)
        if (!category) return document.getElementById('place-search')?.focus()
        useSearchStore.getState().submit(category, center)
        sheet.setStage('map', 2)
        return
      case 'open_pin': {
        // 지도 탭에서 그 핀 카드를 연다 — 목록·지도 핀을 누를 때와 같은 ?pin= 선택이다(#1356). 확정은 사람이 한다.
        const pinId = pin_ids?.[0]
        if (!pinId || (pins && !pins.some((p) => p.id === pinId))) return showToast(CHANGED)
        navigate(`/maps/${mapId}?${new URLSearchParams({ [PIN_PARAM]: pinId })}`)
        return
      }
      case 'open_course':
        // 보고 있던 코스 대신 입력 화면에서 손으로 누를 때와 같은 코스 요청을 한 번 시작한다(CourseBody, #1356).
        useCourseViewStore.getState().close(mapId)
        navigate(`/maps/${mapId}/course?${new URLSearchParams({ [START_PARAM]: '1' })}`)
        return
      case 'open_route':
        openRoute()
        navigate(`/maps/${mapId}/shortlist`)
        return
      default:
        showToast(CHANGED)
    }
  }
}
