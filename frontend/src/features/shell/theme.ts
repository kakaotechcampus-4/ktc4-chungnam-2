import { useSyncExternalStore } from 'react'

/** 화면 모드(#1412). 기기 설정을 따르거나 밝게·어둡게로 고정한다. 고른 값은 이 기기에만 남긴다(localStorage). */
export type ThemeChoice = 'system' | 'light' | 'dark'

export const THEME_CHOICES: { key: ThemeChoice; label: string }[] = [
  { key: 'system', label: '기기 설정' },
  { key: 'light', label: '밝게' },
  { key: 'dark', label: '어둡게' },
]

const KEY = 'pingo-theme'
/** 주소창 색(index.html theme-color) — 지도 위 컨트롤 면(--surface-card)과 이어지게. */
const BAR = { light: '#FFFFFF', dark: '#26282D' }
const listeners = new Set<() => void>()

export function readChoice(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}

const systemDark = () => typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches

/**
 * <html data-theme> 를 정한다 — 색 토큰은 이 값 하나로 갈린다(tokens.css). index.html 의 첫 줄 스크립트가 같은 일을 그리기 전에 한 번 한다(깜빡임 방지).
 */
export function applyTheme(choice: ThemeChoice = readChoice()) {
  const dark = choice === 'dark' || (choice === 'system' && systemDark())
  document.documentElement.dataset.theme = dark ? 'dark' : 'light'
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', dark ? BAR.dark : BAR.light)
}

export function setThemeChoice(choice: ThemeChoice) {
  try {
    if (choice === 'system') localStorage.removeItem(KEY)
    else localStorage.setItem(KEY, choice)
  } catch {
    // 저장이 막힌 창(시크릿 등)이면 이번 화면에만 적용한다.
  }
  current = choice
  applyTheme(choice)
  listeners.forEach((f) => f())
}

let current: ThemeChoice = 'system'

/** 앱 시작 때 한 번. 기기 설정을 따르는 동안은 기기에서 다크를 켜고 끌 때 같이 바뀐다. */
export function initTheme() {
  current = readChoice()
  applyTheme(current)
  if (typeof window.matchMedia === 'function') {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => current === 'system' && applyTheme('system'))
  }
}

export function useThemeChoice(): ThemeChoice {
  return useSyncExternalStore(
    (f) => {
      listeners.add(f)
      return () => listeners.delete(f)
    },
    () => current,
  )
}
