import type { ReactNode } from 'react'
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query'
import { act, renderHook } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { courseKeys } from '@/features/course/queries'
import { mapKeys } from '@/features/maps/queries'
import { shortlistKeys } from '@/features/shortlist/queries'

import { pinKeys } from './queries'
import { STALE_MS, useMapEvents } from './realtime'

vi.mock('@/features/auth/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/features/auth/queries')>()),
  useMeQuery: () => ({ data: { id: 'u_me' } }),
}))

/** 브라우저 EventSource 대신 — 이벤트를 손으로 보낸다. */
class FakeEventSource {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSED = 2
  static all: FakeEventSource[] = []
  readyState = FakeEventSource.CONNECTING
  onopen: (() => void) | null = null
  onerror: (() => void) | null = null
  private listeners = new Map<string, ((e: MessageEvent) => void)[]>()
  readonly url: string
  constructor(url: string) {
    this.url = url
    FakeEventSource.all.push(this)
  }
  addEventListener(type: string, fn: (e: MessageEvent) => void) {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), fn])
  }
  close() {
    this.readyState = FakeEventSource.CLOSED
  }
  open() {
    this.readyState = FakeEventSource.OPEN
    this.onopen?.()
  }
  emit(type: string, data: unknown) {
    const e = new MessageEvent(type, { data: JSON.stringify(data) })
    for (const fn of this.listeners.get(type) ?? []) fn(e)
  }
}

const MAP = 'map_1'
const latest = () => FakeEventSource.all.at(-1)!

function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const invalidate = vi.spyOn(client, 'invalidateQueries')
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter>{children}</MemoryRouter>
    </QueryClientProvider>
  )
  const hook = renderHook(() => useMapEvents(MAP), { wrapper })
  act(() => latest().open())
  const invalidated = () => invalidate.mock.calls.map(([filters]) => JSON.stringify(filters?.queryKey))
  return { client, hook, invalidate, invalidated }
}

const setVisibility = (value: 'visible' | 'hidden') =>
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => value })

beforeEach(() => {
  FakeEventSource.all = []
  vi.stubGlobal('EventSource', FakeEventSource)
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
  setVisibility('visible')
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('실시간 연결 점검(#832, docs/events.md 전달 보장 8번)', () => {
  it('60초 넘게 아무것도 못 받으면 닫고 새로 맺으며, 핀 목록·집계·확정 리스트를 다시 받는다', () => {
    const { hook, invalidated } = setup()
    const first = latest()

    act(() => vi.advanceTimersByTime(STALE_MS))
    expect(FakeEventSource.all).toHaveLength(1)

    act(() => vi.advanceTimersByTime(10_000))
    expect(first.readyState).toBe(FakeEventSource.CLOSED)
    expect(FakeEventSource.all).toHaveLength(2)
    expect(hook.result.current.state).toBe('reconnecting')
    for (const key of [pinKeys.list(MAP), pinKeys.counts(MAP), shortlistKeys.list(MAP)]) {
      expect(invalidated()).toContain(JSON.stringify(key))
    }

    act(() => latest().open())
    expect(hook.result.current.state).toBe('open')
  })

  it('서버 ping(control)이나 이벤트를 받으면 연결을 그대로 둔다', () => {
    setup()
    for (let i = 0; i < 6; i++) {
      act(() => vi.advanceTimersByTime(20_000))
      act(() => latest().emit('control', { type: i % 2 ? 'ping' : 'something_new' }))
    }
    act(() => latest().emit('map.updated', {}))
    act(() => vi.advanceTimersByTime(STALE_MS))
    expect(FakeEventSource.all).toHaveLength(1)
  })

  it('숨겨진 탭에서 타이머가 늦게 돌아도, 다시 보일 때 60초 넘게 조용했으면 새로 맺는다', () => {
    setup()
    setVisibility('hidden')
    // 타이머는 돌지 않고 시계만 간다(숨겨진 탭).
    vi.setSystemTime(Date.now() + STALE_MS + 1)
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(FakeEventSource.all).toHaveLength(1)

    setVisibility('visible')
    act(() => document.dispatchEvent(new Event('visibilitychange')))
    expect(FakeEventSource.all).toHaveLength(2)
  })

  it('브라우저가 재연결을 포기한(CLOSED) 연결은 점검이 다시 맺지 않는다 — 「다시 연결」 버튼 몫이다', () => {
    const { hook } = setup()
    act(() => {
      latest().close()
      latest().onerror?.()
    })
    expect(hook.result.current.state).toBe('closed')
    act(() => vi.advanceTimersByTime(STALE_MS + 10_000))
    expect(FakeEventSource.all).toHaveLength(1)
  })

  it('핀 목록을 아직 받지 않았을 때 온 핀 이벤트는 버리지 않고 목록을 새로 받게 한다', () => {
    const { invalidated } = setup()
    act(() => latest().emit('pin.created', { id: 'pin_9', created_by: 'u_me' }))
    expect(invalidated()).toContain(JSON.stringify(pinKeys.list(MAP)))
  })

  it('지도 정보가 바뀌면 일정도 다시 받는다 — 날짜를 고치면 서버가 기간 밖 일정을 뺀다(#1273)', () => {
    const { invalidated } = setup()
    act(() => latest().emit('map.updated', { map_id: MAP }))
    expect(invalidated()).toContain(JSON.stringify(shortlistKeys.list(MAP)))
  })
})

describe('shortlist.changed 뒤 AI 코스 재조회(#1322)', () => {
  it('열려 있는 최근 코스와 run 상세를 다시 받는다 — 일정이 바뀌면 stale 이 되어 「반영」을 막는다', async () => {
    const { client, invalidated } = setup()
    const fetched = { latest: 0, run: 0 }
    const observe = (queryKey: readonly unknown[], name: keyof typeof fetched) =>
      new QueryObserver(client, { queryKey, queryFn: async () => ({ n: ++fetched[name] }) }).subscribe(() => {})
    const stops = [observe(courseKeys.latest(MAP), 'latest'), observe(courseKeys.run('run_1'), 'run')]
    // 시계가 가짜라 waitFor 의 폴링이 돌지 않는다 — 비동기 작업만 흘려보낸다.
    const settle = () => act(async () => void (await vi.advanceTimersByTimeAsync(10)))
    await settle()
    expect(fetched).toEqual({ latest: 1, run: 1 })

    act(() => latest().emit('shortlist.changed', { item: {}, action: 'reordered' }))
    await settle()
    expect(fetched).toEqual({ latest: 2, run: 2 })
    expect(invalidated()).toContain(JSON.stringify(courseKeys.latest(MAP)))
    stops.forEach((stop) => stop())
  })
})

describe('접속 상태(#1551)', () => {
  it('member.presence 를 받으면 구성원 목록 캐시의 그 사람 online 만 고친다', () => {
    const { client } = setup()
    client.setQueryData(mapKeys.members(MAP), [
      { user_id: 'u_me', role: 'owner', is_guest: false, online: true },
      { user_id: 'u_2', role: 'member', is_guest: false, online: false },
    ])
    act(() => latest().emit('member.presence', { user_id: 'u_2', online: true }))
    expect(client.getQueryData<{ user_id: string; online: boolean }[]>(mapKeys.members(MAP))?.map((m) => m.online)).toEqual([true, true])
  })
})
