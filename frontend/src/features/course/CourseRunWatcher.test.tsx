import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { server } from '@pingo/contracts/mocks/node'
import { afterAll, afterEach, beforeAll, expect, it } from 'vitest'

import { clearTabNews, useTabNews } from '@/features/shell/tabNews'

import { useCourseViewStore } from './courseMapStore'
import CourseRunWatcher from './CourseRunWatcher'

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }))
afterEach(() => {
  server.resetHandlers()
  clearTabNews('m1', 'course')
  useCourseViewStore.setState({ runs: {} })
})
afterAll(() => server.close())

/** 이 run 을 부를 때마다 statuses 를 차례로 돌려준다(마지막은 계속). */
function serve(statuses: string[]) {
  let i = 0
  server.use(http.get('*/course-runs/:id', ({ params }) => HttpResponse.json({ id: params.id, map_id: 'm1', status: statuses[Math.min(i++, statuses.length - 1)], days: [] })))
}


/** 감시 부품을 붙이고, AI 코스 탭의 새 소식을 읽는 훅을 한 번만 그린다. */
function watch() {
  window.history.replaceState({}, '', '/maps/m1/shortlist')
  useCourseViewStore.getState().open('m1', 'r1')
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CourseRunWatcher mapId="m1" />
    </QueryClientProvider>,
  )
  return renderHook(() => useTabNews('m1', 'course')).result
}

it('다른 탭에 있는 동안 짜는 중이던 코스가 끝나면 AI 코스 탭에 새 소식을 단다(#1719)', async () => {
  serve(['running', 'done'])
  const news = watch()
  await waitFor(() => expect(news.current).toBe('AI 코스가 완성됐어요'), { timeout: 5000 })
}, 10_000)

it('처음부터 끝나 있던 코스(예전 코스 다시 열기)에는 달지 않는다', async () => {
  serve(['done'])
  const news = watch()
  await new Promise((r) => setTimeout(r, 300))
  expect(news.current).toBeUndefined()
})
