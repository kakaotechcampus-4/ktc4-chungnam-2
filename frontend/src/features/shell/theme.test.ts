import { afterEach, describe, expect, it, vi } from 'vitest'

import { applyTheme, readChoice, setThemeChoice } from './theme'

const systemIs = (dark: boolean) =>
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: dark && q.includes('dark'), addEventListener: () => {} }) as unknown as MediaQueryList)

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
})

describe('화면 모드(#1412)', () => {
  it('고른 게 없으면 기기 설정을 따른다', () => {
    systemIs(true)
    expect(readChoice()).toBe('system')
    applyTheme()
    expect(document.documentElement.dataset.theme).toBe('dark')
    systemIs(false)
    applyTheme()
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('밝게·어둡게는 기기 설정보다 먼저이고 이 기기에 남는다. 기기 설정으로 돌리면 지운다', () => {
    systemIs(true)
    setThemeChoice('light')
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(readChoice()).toBe('light')
    setThemeChoice('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
    setThemeChoice('system')
    expect(localStorage.getItem('pingo-theme')).toBeNull()
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})
