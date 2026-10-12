import { useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router'

import { FILTER_CATEGORIES, KINDS, OPINIONS, SORTS, type PinCategory, type PinFilters, type PinOpinion, type PinSort } from './model'

/**
 * 마킹 탭 필터(카테고리·올린 사람·정렬)는 주소에 둔다 — 선택한 핀(usePinSelection)과 같은 이유다.
 * 새로고침·공유해도 같은 목록이 보이고, 지도 마커와 목록이 같은 값을 본다.
 */
export function usePinFilters() {
  const [params, setParams] = useSearchParams()

  const filters = useMemo<PinFilters>(() => {
    const category = params.get('category') as PinCategory | null
    const sort = params.get('sort') as PinSort | null
    return {
      category: category && FILTER_CATEGORIES.includes(category) ? category : null,
      createdBy: params.get('by'),
      kind: KINDS.find((k) => k === params.get('kind')) ?? null,
      opinion: (params.get('opinion') as PinOpinion | null) && (params.get('opinion') as string) in OPINIONS ? (params.get('opinion') as PinOpinion) : null,
      sort: sort && sort in SORTS ? sort : 'most',
    }
  }, [params])

  const setFilter = useCallback(
    (key: 'category' | 'by' | 'kind' | 'opinion' | 'sort', value: string | null) => {
      const next = new URLSearchParams(params)
      if (value) next.set(key, value)
      else next.delete(key)
      setParams(next, { replace: true })
    },
    [params, setParams],
  )

  const clear = useCallback(() => {
    const next = new URLSearchParams(params)
    for (const key of ['category', 'by', 'kind', 'opinion', 'sort']) next.delete(key)
    setParams(next, { replace: true })
  }, [params, setParams])

  return { filters, setFilter, clear }
}
