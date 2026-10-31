import { useQueryClient } from '@tanstack/react-query'
import { create } from 'zustand'

import type { Pin } from '@/features/map/model'
import { pinKeys } from '@/features/map/queries'

import { createPinsBulk, previewLinks } from './api'
import { BULK_CHUNK, chunk, extractMapLinks, PREVIEW_CHUNK, rowState, toPinRequest, type ImportRow } from './model'

export type ImportPhase = 'paste' | 'checking' | 'review' | 'saving' | 'done'

/**
 * 카톡 대화에서 가져오기(#578)의 진행. 시트를 닫았다 열어도 이어지게 화면 메모리에만 둔다 —
 * 「하나씩 찍기」로 링크 하나를 검색 시트에서 처리하고 돌아와 나머지를 이어 가기 때문이다.
 * 담는 것은 뽑은 지도 링크와 서버 응답뿐이고, 대화 원문은 담지 않는다.
 */
type ImportState = {
  mapId: string | null
  phase: ImportPhase
  rows: ImportRow[]
  /** 대화에서 찾은 링크 수(중복 제외). rows보다 많으면 앞의 것만 확인했다. */
  found: number
  error: unknown
}

const EMPTY: ImportState = { mapId: null, phase: 'paste', rows: [], found: 0, error: null }

const useImportStore = create<ImportState>(() => EMPTY)
const patch = (p: Partial<ImportState>) => useImportStore.setState(p)
const patchRows = (fn: (rows: ImportRow[]) => ImportRow[]) => useImportStore.setState((s) => ({ rows: fn(s.rows) }))

/** 아직 미리보기를 못 받은 줄을 10개씩 차례로 확인한다. 실패하면 멈추고, 받은 줄은 그대로 둔다. */
async function checkRemaining(mapId: string) {
  patch({ phase: 'checking', error: null })
  const todo = useImportStore.getState().rows.flatMap((r, i) => (r.item ? [] : [i]))
  try {
    for (const part of chunk(todo, PREVIEW_CHUNK)) {
      const { items } = await previewLinks(mapId, part.map((i) => useImportStore.getState().rows[i].url))
      patchRows((rows) =>
        rows.map((r, i) => {
          const item = items.find((it) => part[it.index] === i)
          return item ? { ...r, item, picked: rowState({ ...r, item }) === 'found' } : r
        }),
      )
    }
  } catch (error) {
    patch({ error })
  }
  patch({ phase: 'review' })
}

export function useLinkImport(mapId: string) {
  const queryClient = useQueryClient()
  const state = useImportStore()
  const mine = state.mapId === mapId ? state : { ...EMPTY, mapId }

  return {
    ...mine,
    /** 대화에서 링크를 뽑아 확인을 시작한다. 뽑은 링크가 없으면 false. 대화 원문은 여기서 쓰고 버린다. */
    start(text: string): boolean {
      const { urls, found } = extractMapLinks(text)
      if (urls.length === 0) return false
      useImportStore.setState({ ...EMPTY, mapId, found, rows: urls.map((url) => ({ url, picked: false })) })
      void checkRemaining(mapId)
      return true
    },
    retryCheck: () => void checkRemaining(mapId),
    toggle: (i: number) => patchRows((rows) => rows.map((r, j) => (j === i ? { ...r, picked: !r.picked } : r))),
    markOpened: (i: number) => patchRows((rows) => rows.map((r, j) => (j === i ? { ...r, opened: true } : r))),
    reset: () => useImportStore.setState({ ...EMPTY, mapId }),
    /**
     * 고른 장소를 30개씩 한꺼번에 찍는다. 만든 핀은 목록 캐시에 바로 넣는다(서버가 pin.created도 보내고 같은 id로 덮인다).
     * 실패하면 멈추고, 이미 결과를 받은 줄은 그대로 둔다 — 다시 누르면 남은 줄만 보낸다.
     */
    async save(): Promise<number> {
      patch({ phase: 'saving', error: null })
      let made = 0
      const todo = useImportStore.getState().rows.flatMap((r, i) => {
        const req = r.picked && !r.outcome ? toPinRequest(r) : null
        return req ? [{ i, req }] : []
      })
      try {
        for (const part of chunk(todo, BULK_CHUNK)) {
          const { results } = await createPinsBulk(mapId, part.map((t) => t.req))
          const created = results.flatMap((r) => (r.pin ? [r.pin] : []))
          made += created.length
          queryClient.setQueryData<Pin[]>(pinKeys.list(mapId), (pins) =>
            pins && [...pins.filter((p) => !created.some((c) => c.id === p.id)), ...created],
          )
          patchRows((rows) =>
            rows.map((r, i) => {
              const res = results.find((x) => part[x.index]?.i === i)
              return res ? { ...r, outcome: res.status } : r
            }),
          )
        }
        patch({ phase: 'done' })
      } catch (error) {
        patch({ phase: 'review', error })
      }
      return made
    },
  }
}
