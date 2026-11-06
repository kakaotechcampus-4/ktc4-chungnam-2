import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, filenameFrom } from './api'

describe('filenameFrom (#484 내보내기 파일 이름)', () => {
  it('한글 이름은 filename* 을 풀어서 쓴다', () => {
    expect(filenameFrom(`attachment; filename="shortlist.csv"; filename*=UTF-8''%EC%A0%9C%EC%A3%BC.csv`)).toBe('제주.csv')
  })
  it('filename* 이 없으면 ASCII 이름', () => {
    expect(filenameFrom('attachment; filename="shortlist.txt"')).toBe('shortlist.txt')
  })
  it('헤더가 없으면(다른 오리진이라 가려짐) 없음', () => {
    expect(filenameFrom(null)).toBeUndefined()
  })
})

describe('배포 중 끊김 다시 묻기', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  const gateway = () => new Response('<html>502</html>', { status: 502 })
  const envelope503 = () => Response.json({ code: 'PLACES_UNAVAILABLE', message: '검색 불가' }, { status: 503 })

  function stubFetch(...responses: (() => Response)[]) {
    const fetch = vi.fn()
    responses.forEach((r) => fetch.mockImplementationOnce(async () => r()))
    vi.stubGlobal('fetch', fetch)
    return fetch
  }

  it('조회는 봉투 없는 502가 그치면 그 답을 받는다', async () => {
    vi.useFakeTimers()
    const fetch = stubFetch(gateway, gateway, () => Response.json({ ok: true }))
    const result = api('/auth/me')
    await vi.runAllTimersAsync()
    await expect(result).resolves.toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledTimes(3)
  })

  it('계속 502면 다섯 번 더 묻고 INTERNAL_ERROR로 멈춘다', async () => {
    vi.useFakeTimers()
    const fetch = stubFetch(...Array(6).fill(gateway))
    const result = api('/auth/me')
    const caught = expect(result).rejects.toMatchObject({ status: 502, code: 'INTERNAL_ERROR' })
    await vi.runAllTimersAsync()
    await caught
    expect(fetch).toHaveBeenCalledTimes(6)
  })

  it('쓰기와 서버가 봉투로 준 503은 다시 묻지 않는다', async () => {
    const fetch = stubFetch(gateway, envelope503)
    await expect(api('/maps', { method: 'POST', body: '{}' })).rejects.toMatchObject({ status: 502 })
    await expect(api('/places/search')).rejects.toMatchObject({ code: 'PLACES_UNAVAILABLE' })
    expect(fetch).toHaveBeenCalledTimes(2)
  })
})
