import { useQueryClient } from '@tanstack/react-query'
import { create } from 'zustand'

import { ApiError } from '@/api'
import type { Pin } from '@/features/map/model'
import { pinKeys } from '@/features/map/queries'
import { searchPlaces } from '@/features/search/api'
import type { LatLng } from '@/features/search/model'

import { createPinsBulk, previewLinks } from './api'
import {
  BULK_CHUNK,
  chunk,
  hintOf,
  placeKey,
  PREVIEW_CHUNK,
  rowName,
  rowState,
  sameRoadAddress,
  SEARCH_SHOWN,
  toPinRequest,
  type ImportRow,
  type PlaceSearchResultDto,
} from './model'
import { readShares } from './share'

export type ImportPhase = 'paste' | 'checking' | 'review' | 'saving' | 'done'

/**
 * 카톡 대화에서 가져오기(#578, #1046)의 진행. 시트를 닫았다 열어도 이어지게 화면 메모리에만 둔다 —
 * 「직접 찾기」·「하나씩 찍기」로 검색 시트에 다녀와 나머지를 이어 가기 때문이다.
 * 담는 것은 링크와 공유 글에서 읽은 이름·주소, 서버 응답뿐이고, 대화 원문은 담지 않는다.
 */
type ImportState = {
  mapId: string | null
  phase: ImportPhase
  rows: ImportRow[]
  /** 대화에서 찾은 링크 수(중복 제외). rows보다 많으면 앞의 것만 확인했다. */
  found: number
  /** 이름으로 찾을 때 가까운 순의 기준(지도 핀들의 가운데). */
  near: LatLng | null
  error: unknown
  /** 이름 검색이 호출 상한(429)에 걸려 멈췄다. */
  searchPaused: boolean
}

const EMPTY: ImportState = { mapId: null, phase: 'paste', rows: [], found: 0, near: null, error: null, searchPaused: false }

const useImportStore = create<ImportState>(() => EMPTY)
/** 진행을 처음으로(다른 지도·시험 사이). */
export const resetImport = () => useImportStore.setState(EMPTY)
const patch = (p: Partial<ImportState>) => useImportStore.setState(p)
const patchRow = (i: number, fn: (row: ImportRow) => ImportRow) =>
  useImportStore.setState((s) => ({ rows: s.rows.map((r, j) => (j === i ? fn(r) : r)) }))

/** 아직 미리보기를 못 받은 줄을 10개씩 차례로 확인한다. 실패하면 멈추고, 받은 줄은 그대로 둔다. */
async function checkRemaining(mapId: string) {
  patch({ phase: 'checking', error: null })
  const todo = useImportStore.getState().rows.flatMap((r, i) => (r.item ? [] : [i]))
  try {
    for (const part of chunk(todo, PREVIEW_CHUNK)) {
      const rows = useImportStore.getState().rows
      // hints[i] 는 urls[i] 의 힌트 — 청크마다 같은 순서·같은 길이로 보낸다.
      const { items } = await previewLinks(
        mapId,
        part.map((i) => rows[i].share.url),
        part.map((i) => hintOf(rows[i].share)),
      )
      for (const item of items) {
        const i = part[item.index]
        if (i === undefined) continue
        patchRow(i, (r) => {
          const next = { ...r, item }
          return { ...next, picked: rowState(next) === 'found' }
        })
      }
    }
  } catch (error) {
    patch({ error, phase: 'review' })
    return
  }
  patch({ phase: 'review' })
  await searchRemaining()
}

/**
 * 이름은 아는데 자체 DB 짝이 없는 줄을 이름으로 찾는다(4단 해결의 3·4단계). 결과에서 공유 글 주소와 도로명주소(건물번호까지)가
 * 같은 곳이 정확히 하나면 미리 고른다. 아니면 상위 몇 곳을 고르지 않은 채 보인다 — 근거 없이 자동 확정하지 않는다(가드레일 2).
 * 호출 상한(429)에 걸리면 멈추고, 남은 줄은 「다시 찾기」로 이어 간다.
 */
async function searchRemaining() {
  patch({ searchPaused: false })
  const { rows, near } = useImportStore.getState()
  const todo = rows.flatMap((r, i) => (rowState(r) === 'search' && r.search?.status !== 'done' ? [i] : []))
  for (const i of todo) {
    const row = useImportStore.getState().rows[i]
    const name = rowName(row)
    if (!name) continue
    patchRow(i, (r) => ({ ...r, search: { status: 'loading', results: [] } }))
    try {
      const found = (await searchPlaces(name.slice(0, 50), near)).slice(0, SEARCH_SHOWN)
      const same = found.filter((p) => sameRoadAddress(row.share.address, p.address))
      const pick = same.length === 1 && toPinRequest({ ...row, choice: same[0] }) ? same[0] : null
      patchRow(i, (r) => ({ ...r, search: { status: 'done', results: found }, ...(pick ? { choice: pick, picked: true, auto: true } : {}) }))
    } catch (error) {
      patchRow(i, (r) => ({ ...r, search: { status: 'error', results: [] } }))
      if (error instanceof ApiError && error.status === 429) {
        patch({ searchPaused: true })
        return
      }
    }
  }
}

/** 지도 핀들의 가운데 — 이름으로 찾을 때 이 근처가 먼저 나온다. 핀이 없으면 기준 없이 찾는다. */
export function pinsCenter(pins: Pin[] | undefined): LatLng | null {
  const placed = (pins ?? []).filter((p) => typeof p.lat === 'number' && typeof p.lng === 'number')
  if (placed.length === 0) return null
  return {
    lat: placed.reduce((s, p) => s + p.lat!, 0) / placed.length,
    lng: placed.reduce((s, p) => s + p.lng!, 0) / placed.length,
  }
}

export function useLinkImport(mapId: string) {
  const queryClient = useQueryClient()
  const state = useImportStore()
  const mine = state.mapId === mapId ? state : { ...EMPTY, mapId }

  return {
    ...mine,
    /** 대화에서 링크와 공유 글을 읽어 확인을 시작한다. 뽑은 링크가 없으면 false. 대화 원문은 여기서 쓰고 버린다. */
    start(text: string, near: LatLng | null): boolean {
      const { shares, found } = readShares(text)
      if (shares.length === 0) return false
      useImportStore.setState({ ...EMPTY, mapId, found, near, rows: shares.map((share) => ({ share, picked: false })) })
      void checkRemaining(mapId)
      return true
    },
    retryCheck: () => void checkRemaining(mapId),
    retrySearch: () => void searchRemaining(),
    toggle: (i: number) => patchRow(i, (r) => ({ ...r, picked: !r.picked })),
    /** 주소 후보·이름 검색 후보에서 고른다. null 이면 「여기 없어요」 — 고르지 않은 채로 둔다. */
    choose: (i: number, place: PlaceSearchResultDto | null) =>
      patchRow(i, (r) => ({ ...r, choice: place, picked: place !== null, auto: false })),
    markOpened: (i: number) => patchRow(i, (r) => ({ ...r, opened: true })),
    reset: () => useImportStore.setState({ ...EMPTY, mapId }),
    /**
     * 고른 장소를 30개씩 한꺼번에 찍는다. 다른 링크라도 같은 장소면 한 번만 보낸다(가능하면 번호가 있는 링크의 `link_ref`를 싣는다).
     * 만든 핀은 목록 캐시에 바로 넣는다(서버가 pin.created도 보내고 같은 id로 덮인다).
     * 실패하면 멈추고, 이미 결과를 받은 줄은 그대로 둔다 — 다시 누르면 남은 줄만 보낸다.
     */
    async save(): Promise<number> {
      patch({ phase: 'saving', error: null })
      let made = 0
      const groups = new Map<string, number[]>()
      const rows = useImportStore.getState().rows
      rows.forEach((r, i) => {
        const key = r.picked && !r.outcome && toPinRequest(r) ? placeKey(r) : undefined
        if (key) groups.set(key, [...(groups.get(key) ?? []), i])
      })
      const todo = [...groups.values()].map((group) => {
        const lead = group.find((i) => rows[i].item?.result?.external_id) ?? group[0]
        return { group, req: toPinRequest(rows[lead])! }
      })
      try {
        for (const part of chunk(todo, BULK_CHUNK)) {
          const { results } = await createPinsBulk(mapId, part.map((t) => t.req))
          const created = results.flatMap((r) => (r.pin ? [r.pin] : []))
          made += created.length
          queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) =>
            pins && [...pins.filter((p) => !created.some((c) => c.id === p.id)), ...created],
          )
          for (const res of results) {
            for (const i of part[res.index]?.group ?? []) patchRow(i, (r) => ({ ...r, outcome: res.status }))
          }
        }
        patch({ phase: 'done' })
      } catch (error) {
        patch({ phase: 'review', error })
      }
      return made
    },
  }
}
