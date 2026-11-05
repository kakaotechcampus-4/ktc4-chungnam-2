import { useEffect } from 'react'
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
  mergeRows,
  placeKey,
  PREVIEW_CHUNK,
  rowName,
  rowState,
  sameRoadAddress,
  SEARCH_SHOWN,
  toPinRequest,
  type BulkPinItemResultDto,
  type ImportRow,
  type PlaceSearchResultDto,
} from './model'
import { readShares, type DayRange } from './share'
import { clearImport, loadImport, saveImport } from './storage'

/** idle: 할 일 없음 · checking: 링크 미리보기 중 · saving: 핀 찍는 중. 결과는 같은 목록에 쌓인다(끝난 화면을 따로 두지 않는다, #1045). */
export type ImportPhase = 'idle' | 'checking' | 'saving'

/** 파일 하나를 넣은 결과. noLinks: 그 기간에 지도 링크가 없다 · noDates: 날짜를 하나도 읽지 못했다(내보내기 파일이 아니다, #1139) · full: 목록이 가득 차서 새 링크를 하나도 못 더했다(찍고 완료된 것을 지워야 더할 수 있다). */
export type AddResult = 'added' | 'noNew' | 'noLinks' | 'noDates' | 'full'

type Outcome = NonNullable<BulkPinItemResultDto['status']>

/**
 * 카톡 대화에서 가져오기(#578, #1046, #1045)의 진행. 지도별로 sessionStorage 에 이어 두어 새로고침해도 남는다(storage.ts).
 * 담는 것은 링크와 공유 글에서 읽은 이름·주소, 서버 응답뿐이고, 대화 원문은 담지 않는다.
 * 시트가 열려 있는지(`openFor`)도 여기 둔다 — 버튼이 있는 목록 머리가 검색·핀 상세로 바뀌어도 시트와 「모달 열림」이 따라 사라지지 않게(#1045).
 */
type ImportState = {
  mapId: string | null
  /** 시트가 열린 지도. 닫히면 null. */
  openFor: string | null
  phase: ImportPhase
  rows: ImportRow[]
  /** 지난 파일에서 상한을 넘어 버린 링크가 있었다. */
  truncated: boolean
  /** 이름으로 찾을 때 가까운 순의 기준(지도 핀들의 가운데). */
  near: LatLng | null
  error: unknown
  /** 이름 검색이 호출 상한(429)에 걸려 멈췄다. */
  searchPaused: boolean
  /** 마지막으로 찍은 결과(같은 장소로 묶인 줄은 한 곳). */
  lastSaved: Record<Outcome, number> | null
}

const EMPTY: ImportState = {
  mapId: null,
  openFor: null,
  phase: 'idle',
  rows: [],
  truncated: false,
  near: null,
  error: null,
  searchPaused: false,
  lastSaved: null,
}

const useImportStore = create<ImportState>(() => EMPTY)
const patch = (p: Partial<ImportState>) => useImportStore.setState(p)
/**
 * 줄은 링크로 찾는다(링크마다 한 줄). 순번으로 찾으면 응답을 기다리는 사이 「완료된 것 지우기」·「모두 비우기」로
 * 줄이 당겨졌을 때 다른 줄에 결과가 붙는다(#1116 검토). 지워진 줄의 응답은 버린다.
 */
const patchRow = (url: string, fn: (row: ImportRow) => ImportRow) =>
  useImportStore.setState((s) => ({ rows: s.rows.map((r) => (r.share.url === url ? fn(r) : r)) }))

// 목록이 바뀔 때마다 그 지도의 저장소에 옮긴다. 대화 원문은 애초에 스토어에 없다.
useImportStore.subscribe((s, prev) => {
  if (s.mapId && (s.rows !== prev.rows || s.mapId !== prev.mapId)) saveImport(s.mapId, s.rows)
})

/** 진행을 처음으로(시험 사이). 저장소는 건드리지 않는다. */
export const resetImport = () => useImportStore.setState(EMPTY)

/** 로그아웃(지도 없이)·지도 나가기·삭제 때 목록을 잊는다 — 화면 메모리와 저장소 둘 다. */
export function forgetImport(mapId?: string) {
  clearImport(mapId)
  const s = useImportStore.getState()
  if (!mapId || s.mapId === mapId) useImportStore.setState(EMPTY)
}

export const openImport = (mapId: string) => patch({ openFor: mapId })
export const closeImport = () => patch({ openFor: null })
export const useImportOpen = (mapId: string) => useImportStore((s) => s.openFor === mapId)

/** 이 지도의 목록을 쓸 준비 — 다른 지도의 것이 남아 있으면 바꾸고, 새로고침 뒤면 저장소에서 되살려 다시 확인한다. */
function ensureMap(mapId: string, near: LatLng | null) {
  const s = useImportStore.getState()
  if (s.mapId === mapId) {
    if (!s.near && near) patch({ near })
    return
  }
  const rows = loadImport(mapId)
  useImportStore.setState({ ...EMPTY, openFor: s.openFor, mapId, near, rows })
  if (rows.length > 0) void checkRemaining(mapId)
}

/**
 * 아직 미리보기를 못 받은 줄을 10개씩 차례로 확인한다(찍은 줄 포함 — 이름·「이미 있음」을 다시 받는다). 실패하면 멈추고, 받은 줄은 그대로 둔다.
 * 남은 줄은 매번 목록에서 다시 고른다 — 확인하는 중에 더 붙여넣은 링크도 이 반복이 이어 확인한다(#1116 검토).
 */
async function checkRemaining(mapId: string) {
  if (useImportStore.getState().phase === 'checking') return
  patch({ phase: 'checking', error: null })
  // 한 번 보낸 링크는 다시 보내지 않는다 — 서버가 어떤 항목을 빠뜨려도 반복이 끝난다.
  const sent = new Set<string>()
  try {
    for (;;) {
      const part = useImportStore
        .getState()
        .rows.filter((r) => !r.item && !sent.has(r.share.url))
        .slice(0, PREVIEW_CHUNK)
        .map((r) => r.share)
      if (part.length === 0) break
      for (const share of part) sent.add(share.url)
      // hints[i] 는 urls[i] 의 힌트 — 청크마다 같은 순서·같은 길이로 보낸다.
      const { items } = await previewLinks(
        mapId,
        part.map((share) => share.url),
        part.map(hintOf),
      )
      if (useImportStore.getState().mapId !== mapId) return
      for (const item of items) {
        const url = part[item.index]?.url
        if (url === undefined) continue
        patchRow(url, (r) => {
          const next = { ...r, item }
          if (r.outcome) return next
          // 되살린 줄: 고른 주소 후보를 다시 맞춘다. 처음 받은 줄: 서버가 찾은 곳만 미리 체크.
          const candidate = item.result?.address_candidates?.find((c) => c.place_id === r.choiceId)
          if (candidate) return { ...next, choice: candidate, choiceId: undefined }
          return r.choiceId !== undefined || r.picked ? next : { ...next, picked: rowState(next) === 'found' }
        })
      }
    }
  } catch (error) {
    patch({ error, phase: 'idle' })
    return
  }
  patch({ phase: 'idle' })
  await searchRemaining()
}

/**
 * 이름은 아는데 자체 DB 짝이 없는 줄을 이름으로 찾는다(4단 해결의 3·4단계). 결과에서 공유 글 주소와 도로명주소(건물번호까지)가
 * 같은 곳이 정확히 하나면 미리 고른다. 아니면 상위 몇 곳을 고르지 않은 채 보인다 — 근거 없이 자동 확정하지 않는다(가드레일 2).
 * 되살린 줄은 저장해 둔 고른 장소 id로 다시 맞춘다. 호출 상한(429)에 걸리면 멈추고, 남은 줄은 「이어서 찾기」로 이어 간다.
 */
async function searchRemaining() {
  patch({ searchPaused: false })
  const { rows, near, mapId } = useImportStore.getState()
  // 찾는 중인 줄은 고르지 않는다 — 다른 확인이 끝나며 이 함수가 또 불려도 같은 이름을 두 번 찾지 않는다.
  const todo = rows.flatMap((r) => (!r.outcome && rowState(r) === 'search' && (!r.search || r.search.status === 'error') ? [r.share.url] : []))
  for (const url of todo) {
    const row = useImportStore.getState().rows.find((r) => r.share.url === url)
    const name = row && rowName(row)
    if (!row || !name) continue
    patchRow(url, (r) => ({ ...r, search: { status: 'loading', results: [] } }))
    try {
      const found = (await searchPlaces(name.slice(0, 50), near)).slice(0, SEARCH_SHOWN)
      if (useImportStore.getState().mapId !== mapId) return
      const saved = row.choiceId ? found.find((p) => p.place_id === row.choiceId) : undefined
      const same = found.filter((p) => sameRoadAddress(row.share.address, p.address))
      const pick = saved ? null : same.length === 1 && toPinRequest({ ...row, choice: same[0] }) ? same[0] : null
      patchRow(url, (r) => ({
        ...r,
        search: { status: 'done', results: found },
        choiceId: undefined,
        ...(saved ? { choice: saved } : pick ? { choice: pick, picked: true, auto: true } : {}),
      }))
    } catch (error) {
      patchRow(url, (r) => ({ ...r, search: { status: 'error', results: [] } }))
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

export function useLinkImport(mapId: string, near: LatLng | null = null) {
  const queryClient = useQueryClient()
  const state = useImportStore()
  // 이 지도의 목록이 아니면(처음·다른 지도·새로고침 뒤) 바꾼다 — 새로고침 뒤면 저장소에서 되살려 다시 확인한다.
  useEffect(() => ensureMap(mapId, near), [mapId, near])
  const mine = state.mapId === mapId ? state : { ...EMPTY, mapId }

  return {
    ...mine,
    /**
     * 대화 파일에서 고른 기간의 링크와 공유 글을 읽어 목록에 더한다 — 이미 있는 링크는 한 줄로 합치고 새 링크만 확인한다(#1045, #1139).
     * 대화 원문과 기간은 여기서 쓰고 버린다.
     */
    add(text: string, range: DayRange): AddResult {
      ensureMap(mapId, near)
      const { shares, found, dated } = readShares(text, range)
      if (!dated) return 'noDates'
      if (shares.length === 0) return 'noLinks'
      const merged = mergeRows(useImportStore.getState().rows, shares)
      // 누적 상한(50줄)이 이미 찼다면 새 링크가 하나도 안 들어간다 — 「더했다」고 하지 말고 따로 알린다. 기간을 좁혀도 풀리지 않는다.
      if (merged.added === 0 && merged.truncated) {
        patch({ truncated: true })
        return 'full'
      }
      // 파일 하나에서 상한을 넘은 링크(readShares 가 자른 것)도 넘친 것으로 센다.
      patch({ rows: merged.rows, truncated: merged.truncated || found > shares.length, lastSaved: null })
      // 이미 있는 링크만 읽었으면(같은 파일을 다시 넣는 등) 목록이 그대로라 따로 알린다.
      if (merged.added === 0) return 'noNew'
      void checkRemaining(mapId)
      return 'added'
    },
    retryCheck: () => void checkRemaining(mapId),
    retrySearch: () => void searchRemaining(),
    toggle: (url: string) => patchRow(url, (r) => ({ ...r, picked: !r.picked })),
    /** 주소 후보·이름 검색 후보에서 고른다. null 이면 「여기 없어요」 — 고르지 않은 채로 둔다. */
    choose: (url: string, place: PlaceSearchResultDto | null) =>
      patchRow(url, (r) => ({ ...r, choice: place, choiceId: undefined, picked: place !== null, auto: false })),
    markOpened: (url: string) => patchRow(url, (r) => ({ ...r, opened: true })),
    /** 찍었거나 이미 지도에 있던 줄을 지운다. */
    clearDone: () =>
      useImportStore.setState((s) => ({ rows: s.rows.filter((r) => !r.outcome && rowState(r) !== 'already'), lastSaved: null })),
    /** 목록을 모두 비운다(지도의 핀은 그대로). */
    clearAll: () => useImportStore.setState((s) => ({ ...EMPTY, openFor: s.openFor, mapId, near: s.near })),
    /**
     * 고른 장소를 30개씩 한꺼번에 찍는다. 다른 링크라도 같은 장소면 한 번만 보낸다(가능하면 번호가 있는 링크의 `link_ref`를 싣는다).
     * 만든 핀은 목록 캐시에 바로 넣는다(서버가 pin.created도 보내고 같은 id로 덮인다).
     * 실패하면 멈추고, 이미 결과를 받은 줄은 그대로 둔다 — 다시 누르면 남은 줄만 보낸다.
     */
    async save(): Promise<number> {
      patch({ phase: 'saving', error: null })
      let made = 0
      const tally: Record<Outcome, number> = { created: 0, duplicate: 0, rejected: 0 }
      const groups = new Map<string, ImportRow[]>()
      for (const r of useImportStore.getState().rows) {
        const key = r.picked && !r.outcome && toPinRequest(r) ? placeKey(r) : undefined
        if (key) groups.set(key, [...(groups.get(key) ?? []), r])
      }
      const todo = [...groups.values()].map((group) => {
        const lead = group.find((r) => r.item?.result?.external_id) ?? group[0]
        return { urls: group.map((r) => r.share.url), req: toPinRequest(lead)! }
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
            tally[res.status] += 1
            for (const url of part[res.index]?.urls ?? []) patchRow(url, (r) => ({ ...r, outcome: res.status }))
          }
        }
        patch({ phase: 'idle', lastSaved: tally })
      } catch (error) {
        patch({ phase: 'idle', error, lastSaved: made > 0 ? tally : null })
      }
      return made
    },
  }
}
