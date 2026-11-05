import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@pingo/contracts/mocks/node'
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest'

import { forgetImport, useLinkImport } from './queries'

const MAP = 'map_1'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  forgetImport()
})
afterAll(() => server.close())

/** 손으로 여는 문 — 응답을 원하는 때에 보낸다. */
function gate() {
  let open!: () => void
  const wait = new Promise<void>((r) => (open = r))
  return { wait, open }
}

/** 미리보기: 링크가 /a 로 끝나면 이미 지도에 있음, 나머지는 자체 DB 짝 없음(이름으로 찾을 곳). */
function previewHandler(before?: Promise<void>) {
  return http.post('*/maps/:mapId/pins/link-preview', async ({ request }) => {
    const { urls } = (await request.json()) as { urls: string[] }
    await before
    return HttpResponse.json({
      items: urls.map((url, index) =>
        url.endsWith('/a')
          ? { index, status: 'ok', already_pinned_pin_id: 'pin_a', result: { provider: 'google', matches: [], needs_search_query: false } }
          : { index, status: 'ok', result: { provider: 'google', matches: [], needs_search_query: false } },
      ),
    })
  })
}

const place = (id: string) => ({ place_id: id, place_name: `${id} 가게`, lat: 37.5, lng: 127, category: '음식점', address: `서울 중구 ${id}로 1` })

function renderImport() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>
  return renderHook(() => useLinkImport(MAP), { wrapper })
}

const row = (rows: ReturnType<typeof useLinkImport>['rows'], url: string) => rows.find((r) => r.share.url === url)

/** 카톡 「대화 내보내기」 .txt 모양 — 줄마다 메시지 하나(#1139). 기간은 그 날짜부터 대화 끝까지. */
const RANGE = { from: '2026-11-02' }
const talk = (...lines: string[]) => lines.map((l) => `2026년 11월 2일 오전 1:00, 친구A : ${l}`).join('\n')

describe('가져오기 목록이 바뀌는 중에 온 응답(#1116 검토)', () => {
  it('이름 검색 중에 「완료된 것 지우기」를 눌러도 결과는 그 링크의 줄에 붙는다', async () => {
    const gB = gate()
    server.use(
      previewHandler(),
      http.get('*/places/search', async ({ request }) => {
        const q = new URL(request.url).searchParams.get('q')
        if (q === 'B집') await gB.wait
        return HttpResponse.json([place(q === 'B집' ? 'pb' : 'pc')])
      }),
    )
    const { result } = renderImport()
    act(() => {
      result.current.add(talk('A집 - https://maps.app.goo.gl/a', 'B집 - https://maps.app.goo.gl/b', 'C집 - https://maps.app.goo.gl/c'), RANGE)
    })
    await waitFor(() => expect(row(result.current.rows, 'https://maps.app.goo.gl/b')?.search?.status).toBe('loading'))

    act(() => result.current.clearDone()) // 이미 지도에 있는 A 를 지운다
    expect(result.current.rows).toHaveLength(2)
    gB.open()

    await waitFor(() => expect(row(result.current.rows, 'https://maps.app.goo.gl/c')?.search?.status).toBe('done'))
    expect(row(result.current.rows, 'https://maps.app.goo.gl/b')?.search?.results.map((p) => p.place_id)).toEqual(['pb'])
    expect(row(result.current.rows, 'https://maps.app.goo.gl/c')?.search?.results.map((p) => p.place_id)).toEqual(['pc'])
  })

  it('링크를 확인하는 중에 더 붙여넣은 링크도 확인한다', async () => {
    const first = gate()
    server.use(previewHandler(first.wait), http.get('*/places/search', () => HttpResponse.json([])))
    const { result } = renderImport()
    act(() => {
      result.current.add(talk('B집 - https://maps.app.goo.gl/b'), RANGE)
    })
    await waitFor(() => expect(result.current.phase).toBe('checking'))
    act(() => {
      result.current.add(talk('C집 - https://maps.app.goo.gl/c'), RANGE)
    })
    first.open()

    await waitFor(() => expect(result.current.rows.every((r) => r.item)).toBe(true))
  })
})
